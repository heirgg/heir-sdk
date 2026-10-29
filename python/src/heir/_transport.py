"""What every call shares, whether sent synchronously or asynchronously: URL building, authentication, caching,
retry decisions and error mapping. The two clients add only the sending and the sleeping."""

from __future__ import annotations

import json
import random
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from ._errors import HeirAPIError, HeirConnectionError, HeirTimeoutError
from ._version import __version__

DEFAULT_BASE_URL = "https://api.heir.gg"
MAX_CACHE_ENTRIES = 1000
_MAX_AGE = re.compile(r"\bmax-age=(\d+)", re.IGNORECASE)
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


@dataclass
class _Prepared:
    url: str
    headers: dict[str, str]
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
    ) -> None:
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.max_retry_delay = max_retry_delay
        self.timeout = timeout
        self.cache_enabled = cache
        self.user_agent = f"heir-sdk-python/{__version__}" + (f" {user_agent}" if user_agent else "")
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self.now = time.monotonic

    # -- building --

    def url(self, call: Call) -> str:
        url = self.base_url + call.path
        query = {name: str(value) for name, value in (call.query or {}).items() if value is not None}
        return url + "?" + urlencode(query) if query else url

    def prepare(self, call: Call, options: RequestOptions) -> _Prepared:
        url = self.url(call)
        use_cache = call.cacheable and self.cache_enabled and not options.no_cache
        cache_key = ("key " if self.api_key else "anon ") + url if use_cache else None
        cached = self._get(cache_key) if cache_key else None
        headers = dict(options.headers or {})
        headers["Accept"] = "application/json"
        content = None
        if call.body is not None:
            content = json.dumps(encode(call.body), separators=(",", ":")).encode()
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
            prepared.attempt += 1
            return backoff(prepared.attempt - 1)
        wrapped.__cause__ = error
        return wrapped

    def outcome(self, prepared: _Prepared, call: Call, response: httpx.Response) -> bytes | float | HeirAPIError:
        """After an answer: the body to decode, how long to wait before trying again, or the error to raise."""
        if response.status_code == 304 and prepared.cached:
            self._put(
                prepared.cache_key,
                _CacheEntry(prepared.cached.etag, prepared.cached.body, self._fresh_until(response.headers)),
            )
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
            return self._cache.get(key)

    def _put(self, key: str | None, entry: _CacheEntry) -> None:
        if key is None:
            return
        with self._lock:
            if len(self._cache) >= MAX_CACHE_ENTRIES:
                self._cache.clear()
            self._cache[key] = entry

    def _store(self, key: str, headers: httpx.Headers, body: bytes) -> None:
        control = headers.get("cache-control", "")
        if "no-store" in control.lower():
            return
        etag = headers.get("etag")
        until = self._fresh_until(headers)
        if not etag and not until:
            return
        self._put(key, _CacheEntry(etag, body, until))

    def _fresh_until(self, headers: httpx.Headers) -> float:
        match = _MAX_AGE.search(headers.get("cache-control", ""))
        return self.now() + int(match.group(1)) if match else 0.0


def encode(body: Any) -> Any:
    """A request body as JSON data: a model as the API spells it, with only the fields that were set."""
    if isinstance(body, BaseModel):
        return body.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return body


def decode(model: type[ModelT], body: bytes) -> ModelT:
    return model.model_validate_json(body)


def backoff(attempt: int) -> float:
    """0.5 s, 1 s, 2 s, ... with jitter, capped at 8 s."""
    return float(min(8.0, 0.5 * 2**attempt) * (0.75 + random.random() * 0.5))
