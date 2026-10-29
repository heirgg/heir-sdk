"""The clients: ``Heir`` for synchronous code, ``AsyncHeir`` for asyncio (or any anyio backend)."""

from __future__ import annotations

import time
from types import TracebackType
from typing import TypeVar

import anyio
import httpx
from pydantic import BaseModel

from ._errors import HeirAPIError
from ._league import AsyncLeague, League
from ._stats import AsyncStats, Stats
from ._transport import DEFAULT_BASE_URL, Call, RequestOptions, Transport, decode

ModelT = TypeVar("ModelT", bound=BaseModel)

_OPTIONS_DOC = """
    Args:
        api_key: A League developer key, from Manage League, Developer, API keys. Leave it out to read League data
            without one (120 requests a minute per address). Call from your server: never put a key in a game client
            or browser.
        base_url: Where the API is. The default is the production API.
        http_client: Your own httpx client (a proxy, a transport, a fake for tests). You then own its lifetime and
            its timeout.
        max_retries: How many times a request is sent again after a 429, a 503, or (for a read or a write carrying an
            Idempotency-Key) a connection failure or gateway error, waiting as Retry-After says or with increasing
            backoff. Default 2.
        max_retry_delay: The longest the client waits before one retry, in seconds. A Retry-After beyond it is not
            waited for: the error is raised with ``retry_after`` set. Default 30.
        timeout: How long one attempt may take, in seconds, before it fails with HeirTimeoutError. Default 30.
        cache: Keep League reads as the API's Cache-Control allows (a minute) and revalidate them with ETag, so a
            server asking on every event does not spend its request allowance. Default True. Paginated and stat
            answers are never cached: the API marks them no-store.
        user_agent: Added to the User-Agent, to say which integration is calling.
"""


class Heir:
    """The Heir API client.

    ::

        heir = Heir(api_key=os.environ["HEIR_API_KEY"])
        nacl = heir.league("nacl")
        answer = nacl.player("mordhau", "A1B2C3D4E5F67890")
        for roster in nacl.rosters():
            print(roster.name, roster.team_mmr)

    Reads work without a key. Eligibility checks and stat submission need the League's developer key.
    """

    __doc__ = (__doc__ or "") + _OPTIONS_DOC

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        http_client: httpx.Client | None = None,
        max_retries: int = 2,
        max_retry_delay: float = 30.0,
        timeout: float | None = 30.0,
        cache: bool = True,
        user_agent: str | None = None,
    ) -> None:
        self._transport = Transport(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            max_retry_delay=max_retry_delay,
            timeout=timeout,
            cache=cache,
            user_agent=user_agent,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        self._sleep = time.sleep
        #: Stat submission for the key's League.
        self.stats = Stats(self)

    def league(self, ref: str) -> League:
        """A League's public reads, by vanity name (``heir.gg/nacl``) or Discord server ID."""
        return League(self, ref)

    @property
    def authenticated(self) -> bool:
        """Whether this client sends a developer key."""
        return self._transport.api_key is not None

    def clear_cache(self) -> None:
        """Forget every cached League read."""
        self._transport.clear_cache()

    def close(self) -> None:
        """Close the HTTP client this client made. One passed in stays yours."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Heir:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def _send(self, call: Call, model: type[ModelT], options: RequestOptions | None = None) -> ModelT:
        prepared = self._transport.prepare(call, options or RequestOptions())
        fresh = self._transport.fresh(prepared)
        if fresh is not None:
            return decode(model, fresh)
        while True:
            try:
                response = self._http.request(
                    call.method, prepared.url, headers=prepared.headers, content=prepared.content
                )
            except httpx.HTTPError as error:
                decision = self._transport.failure(prepared, call, error)
                if isinstance(decision, Exception):
                    raise decision from error
                self._sleep(decision)
                continue
            outcome = self._transport.outcome(prepared, call, response)
            if isinstance(outcome, bytes):
                return decode(model, outcome)
            if isinstance(outcome, HeirAPIError):
                raise outcome
            self._sleep(outcome)


class AsyncHeir:
    """The Heir API client for asyncio or any anyio backend. Calls are awaited; lists are walked with ``async for``.

    ::

        async with AsyncHeir(api_key=os.environ["HEIR_API_KEY"]) as heir:
            page = await heir.league("nacl").rosters()
            async for roster in page:
                print(roster.name)
    """

    __doc__ = (__doc__ or "") + _OPTIONS_DOC

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        max_retry_delay: float = 30.0,
        timeout: float | None = 30.0,
        cache: bool = True,
        user_agent: str | None = None,
    ) -> None:
        self._transport = Transport(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            max_retry_delay=max_retry_delay,
            timeout=timeout,
            cache=cache,
            user_agent=user_agent,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._sleep = anyio.sleep
        #: Stat submission for the key's League.
        self.stats = AsyncStats(self)

    def league(self, ref: str) -> AsyncLeague:
        """A League's public reads, by vanity name (``heir.gg/nacl``) or Discord server ID."""
        return AsyncLeague(self, ref)

    @property
    def authenticated(self) -> bool:
        """Whether this client sends a developer key."""
        return self._transport.api_key is not None

    def clear_cache(self) -> None:
        """Forget every cached League read."""
        self._transport.clear_cache()

    async def aclose(self) -> None:
        """Close the HTTP client this client made. One passed in stays yours."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncHeir:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.aclose()

    async def _send(self, call: Call, model: type[ModelT], options: RequestOptions | None = None) -> ModelT:
        prepared = self._transport.prepare(call, options or RequestOptions())
        fresh = self._transport.fresh(prepared)
        if fresh is not None:
            return decode(model, fresh)
        while True:
            try:
                response = await self._http.request(
                    call.method, prepared.url, headers=prepared.headers, content=prepared.content
                )
            except httpx.HTTPError as error:
                decision = self._transport.failure(prepared, call, error)
                if isinstance(decision, Exception):
                    raise decision from error
                await self._sleep(decision)
                continue
            outcome = self._transport.outcome(prepared, call, response)
            if isinstance(outcome, bytes):
                return decode(model, outcome)
            if isinstance(outcome, HeirAPIError):
                raise outcome
            await self._sleep(outcome)
