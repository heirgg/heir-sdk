"""What every call shares, whether sent synchronously or asynchronously: URL building, authentication, caching,
retry decisions and error mapping. The two clients add only the sending and the sleeping."""

from __future__ import annotations

import json
import math
import random
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Literal, TypeVar
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ValidationError

from ._errors import HeirAPIError, HeirConnectionError, HeirInputError, HeirProtocolError, HeirTimeoutError
from ._version import __version__

DEFAULT_BASE_URL = "https://api.heir.gg"
MAX_CACHE_ENTRIES = 1000
_RETRY_STATUSES = {429, 503}
_RETRY_STATUSES_IF_IDEMPOTENT = {500, 502, 504}

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class Call:
    """One API call as the resources describe it to the transport."""

    method: Literal["GET", "POST"]
    #: The path with its parameters already escaped, such as /public/v1/leagues/nacl/rosters.
    path: str
    query: Mapping[str, str | int | None] | None = None
    body: Any = None
    #: Safe to send again after a connection failure or gateway error: every read, and a write carrying an
    # Idempotency-Key.
    idempotent: bool = False
    #: A read whose answer may be kept as its Cache-Control says.
    cacheable: bool = False
    idempotency_key: str | None = None


@dataclass
class RequestOptions:
    """Options one call may take."""

    headers: Mapping[str, str] | None = None
    #: True to ask the API even when a fresh cached answer exists.
    no_cache: bool = False


@dataclass
class _CacheEntry:
    etag: str | None
    body: bytes
    #: When the entry stops being served without asking the API, on the monotonic clock; 0 means always revalidate.
    fresh_until: float = 0.0
    headers: httpx.Headers = field(default_factory=httpx.Headers)


@dataclass
class _Prepared:
    url: str
    headers: httpx.Headers
    content: bytes | None
    cache_key: str | None
    cached: _CacheEntry | None = None
    max_retries: int = 0
    attempt: int = field(default=0)


class Transport:
    """The shared half of a client. It never does I/O."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        max_retries: int,
        max_retry_delay: float,
        timeout: float | None,
        cache: bool,
        user_agent: str | None,
        owns_timeout: bool = True,
    ) -> None:
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            raise HeirInputError("max_retries must be a non-negative integer")
        _duration("max_retry_delay", max_retry_delay, allow_zero=True)
        if timeout is not None:
            _duration("timeout", timeout, allow_zero=False)
        if not isinstance(cache, bool):
            raise HeirInputError("cache must be a boolean")
        if api_key is not None and not isinstance(api_key, str):
            raise HeirInputError("api_key must be a string or None")
        if user_agent is not None and not isinstance(user_agent, str):
            raise HeirInputError("user_agent must be a string or None")
        if not isinstance(base_url, str):
            raise HeirInputError("base_url must be a string")
        try:
            parsed = httpx.URL(base_url)
        except (TypeError, ValueError, httpx.InvalidURL) as error:
            raise HeirInputError("base_url must be an absolute HTTP or HTTPS URL") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.host
            or parsed.userinfo
            or parsed.query
            or parsed.fragment
            or "?" in base_url
            or "#" in base_url
        ):
            raise HeirInputError(
                "base_url must be an absolute HTTP or HTTPS URL without credentials, query or fragment"
            )
        if any("\r" in value or "\n" in value for value in (api_key or "", user_agent or "")):
            raise HeirInputError("api_key and user_agent must not contain line breaks")
        try:
            (api_key or "").encode("ascii")
            (user_agent or "").encode("ascii")
        except UnicodeEncodeError as error:
            raise HeirInputError("api_key and user_agent must contain ASCII header values") from error
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.base_url = str(parsed).rstrip("/")
        self.max_retries = max_retries
        self.max_retry_delay = max_retry_delay
        # An injected HTTP client can use different limits for each phase or request. Its effective timeout is
        # unknown here; do not report the SDK option as though it governed that client.
        self.timeout = timeout if owns_timeout else None
        self.cache_enabled = cache
        self.user_agent = f"heir-sdk-python/{__version__}" + (f" {user_agent}" if user_agent else "")
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self.now = time.monotonic
        self.wall_now = time.time

    # -- building --

    def url(self, call: Call) -> str:
        url = self.base_url + call.path
        query = {name: str(value) for name, value in (call.query or {}).items() if value is not None}
        return url + "?" + urlencode(query) if query else url

    def prepare(self, call: Call, options: RequestOptions) -> _Prepared:
        url = self.url(call)
        use_cache = call.cacheable and self.cache_enabled and not options.no_cache and not options.headers
        cache_key = ("key " if self.api_key else "anon ") + url if use_cache else None
        cached = self._get(cache_key) if cache_key else None
        try:
            headers = httpx.Headers(options.headers or {})
            if any("\r" in value or "\n" in value for value in headers.values()):
                raise ValueError("header values must not contain line breaks")
        except (TypeError, ValueError) as error:
            raise HeirInputError("Request headers must contain valid string names and values") from error
        headers["Accept"] = "application/json"
        content = None
        if call.body is not None:
            try:
                content = json.dumps(encode(call.body), separators=(",", ":"), allow_nan=False).encode()
            except (TypeError, ValueError) as error:
                raise HeirInputError("The request could not be encoded as JSON") from error
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if call.idempotency_key:
            headers["Idempotency-Key"] = call.idempotency_key
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        headers["User-Agent"] = self.user_agent
        return _Prepared(
            url=url, headers=headers, content=content, cache_key=cache_key, cached=cached, max_retries=self.max_retries
        )

    def fresh(self, prepared: _Prepared) -> bytes | None:
        """A cached answer that is still fresh, needing no request at all."""
        if prepared.cached and prepared.cached.fresh_until > self.now():
            return prepared.cached.body
        return None

    # -- deciding --

    def failure(self, prepared: _Prepared, call: Call, error: Exception) -> float | Exception:
        """After a failed attempt: how long to wait before the next one, or the error to raise."""
        if isinstance(error, httpx.TimeoutException):
            return HeirTimeoutError(prepared.url, self.timeout)
        wrapped: Exception = (
            HeirConnectionError(f"Could not reach {prepared.url}: {error}")
            if isinstance(error, httpx.HTTPError)
            else error
        )
        if isinstance(error, httpx.HTTPError) and call.idempotent and prepared.attempt < prepared.max_retries:
            delay = backoff(prepared.attempt)
            if delay <= self.max_retry_delay:
                prepared.attempt += 1
                return delay
        wrapped.__cause__ = error
        return wrapped

    def outcome(self, prepared: _Prepared, call: Call, response: httpx.Response) -> bytes | float | HeirAPIError:
        """After an answer: the body to decode, how long to wait before trying again, or the error to raise."""
        if response.status_code == 304 and prepared.cached:
            headers = httpx.Headers(prepared.cached.headers)
            # A newly validated response starts a new age calculation. Do not reuse its previous Age value.
            headers.pop("age", None)
            headers.pop("date", None)
            headers.update(response.headers)
            if prepared.cache_key:
                self._store(prepared.cache_key, headers, prepared.cached.body)
            return prepared.cached.body
        if 200 <= response.status_code < 300:
            if prepared.cache_key:
                self._store(prepared.cache_key, response.headers, response.content)
            return response.content
        error = HeirAPIError.from_response(response)
        retryable = error.status_code in _RETRY_STATUSES or (
            call.idempotent and error.status_code in _RETRY_STATUSES_IF_IDEMPOTENT
        )
        if retryable and prepared.attempt < prepared.max_retries:
            delay = error.retry_after if error.retry_after is not None else backoff(prepared.attempt)
            if delay <= self.max_retry_delay:
                prepared.attempt += 1
                return delay
        return error

    # -- caching --

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _get(self, key: str) -> _CacheEntry | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                self._cache.move_to_end(key)
            return entry

    def evict(self, key: str | None) -> None:
        """Discard an invalidated or undecodable cached response."""
        if key is not None:
            with self._lock:
                self._cache.pop(key, None)

    def _put(self, key: str | None, entry: _CacheEntry) -> None:
        if key is None:
            return
        with self._lock:
            if key not in self._cache and len(self._cache) >= MAX_CACHE_ENTRIES:
                self._cache.popitem(last=False)
            self._cache[key] = entry
            self._cache.move_to_end(key)

    def _store(self, key: str, headers: httpx.Headers, body: bytes) -> None:
        control = _cache_control(headers)
        if "no-store" in control or headers.get("vary", "").strip():
            self.evict(key)
            return
        etag = headers.get("etag")
        until = self._fresh_until(headers)
        if not etag and not until:
            self.evict(key)
            return
        self._put(key, _CacheEntry(etag, body, until, httpx.Headers(headers)))

    def _fresh_until(self, headers: httpx.Headers) -> float:
        control = _cache_control(headers)
        if "no-cache" in control:
            return 0.0
        try:
            max_age = float(int(control.get("max-age") or "0"))
            age = max(0.0, float(int(headers.get("age", "0"))))
        except (ValueError, OverflowError):
            return 0.0
        apparent_age = 0.0
        if date := headers.get("date"):
            try:
                at = parsedate_to_datetime(date)
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                apparent_age = max(0.0, self.wall_now() - at.timestamp())
            except (TypeError, ValueError, OverflowError):
                pass
        remaining = max_age - max(age, apparent_age)
        return self.now() + remaining if remaining > 0 else 0.0


def encode(body: Any) -> Any:
    """Encode explicit fields and changed mutable defaults, without introducing unset optional nulls."""
    if isinstance(body, BaseModel):
        try:
            return body.model_dump(mode="json", by_alias=True, include=_included_fields(body))
        except (TypeError, ValueError) as error:
            raise HeirInputError("The request model could not be encoded as JSON") from error
    return body


def decode(model: type[ModelT], body: bytes) -> ModelT:
    try:
        return model.model_validate_json(body)
    except ValidationError as error:
        raise HeirProtocolError(f"The API returned an invalid {model.__name__} response", body) from error


def validate_request(model: type[ModelT], value: Any) -> ModelT:
    """Validate request input at the SDK boundary while retaining Pydantic's detailed cause."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise HeirInputError(f"Invalid {model.__name__} request") from error


def _included_fields(value: Any) -> Any:
    if isinstance(value, BaseModel):
        fields = type(value).model_fields
        included = {name for name in value.model_fields_set if name in fields and hasattr(value, name)}
        for name, definition in type(value).model_fields.items():
            if not hasattr(value, name):
                continue
            current = getattr(value, name)
            if isinstance(current, (dict, list, set, BaseModel)) and current != definition.get_default(
                call_default_factory=True
            ):
                included.add(name)
        selected = {name: _included_fields(getattr(value, name)) for name in included}
        selected.update({name: _included_fields(item) for name, item in (value.model_extra or {}).items()})
        return selected
    if isinstance(value, dict):
        return {key: _included_fields(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return {index: _included_fields(item) for index, item in enumerate(value)}
    return True


def _duration(name: str, value: float, *, allow_zero: bool) -> None:
    try:
        finite = isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        finite = False
    if (
        isinstance(value, bool)
        or not finite
        or value > threading.TIMEOUT_MAX
        or (value < 0 if allow_zero else value <= 0)
    ):
        kind = "non-negative" if allow_zero else "positive"
        raise HeirInputError(f"{name} must be a finite {kind} number no greater than {threading.TIMEOUT_MAX} seconds")


def _cache_control(headers: httpx.Headers) -> dict[str, str | None]:
    directives: dict[str, str | None] = {}
    for part in headers.get("cache-control", "").split(","):
        name, separator, value = part.strip().partition("=")
        directives[name.lower()] = value.strip().strip('"') if separator else None
    return directives


def backoff(attempt: int) -> float:
    """0.5 s, 1 s, 2 s, ... with jitter, capped at 8 s."""
    return float(min(8.0, 0.5 * 2 ** min(attempt, 4) * (0.75 + random.random() * 0.5)))
