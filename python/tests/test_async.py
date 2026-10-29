from __future__ import annotations

import httpx
import pytest

from heir import AsyncHeir, HeirAPIError

from .fake_api import PLAYER, FakeAPI, api_error, respond, roster

pytestmark = pytest.mark.anyio


async def test_async_reads_and_errors() -> None:
    api = FakeAPI(respond(200, PLAYER), api_error(404, "league-not-found"))
    async with AsyncHeir(http_client=httpx.AsyncClient(transport=api.transport()), api_key="k") as heir:
        answer = await heir.league("nacl").player("mordhau", "A1B2C3D4E5F67890")
        assert answer.player is not None and answer.player.display_name == "Ada"
        assert api.requests[0].headers["authorization"] == "Bearer k"
        with pytest.raises(HeirAPIError) as caught:
            await heir.league("nope").config()
        assert caught.value.code == "league-not-found"


async def test_async_pagination_and_retry() -> None:
    api = FakeAPI(
        api_error(429, "rate-limited", "Slow down.", {"retry-after": "0"}),
        respond(200, {"rosters": [roster("a")], "page": 0, "pageSize": 1, "hasMore": True, "nextToken": "t1"}),
        respond(200, {"rosters": [roster("b")], "page": 1, "pageSize": 1, "hasMore": False, "nextToken": None}),
    )
    heir = AsyncHeir(http_client=httpx.AsyncClient(transport=api.transport()))
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    heir._sleep = sleep
    page = await heir.league("nacl").rosters(page_size=1)
    assert [r.name async for r in page] == ["a", "b"]
    assert sleeps == [0.0] and api.calls == 3
    assert page.has_more and page.next_token == "t1"
    await heir.aclose()


async def test_async_tracking_write() -> None:
    api = FakeAPI(respond(200, {"matchId": "m1", "created": True, "approval": "manual", "replayed": False}))
    async with AsyncHeir(http_client=httpx.AsyncClient(transport=api.transport()), api_key="k") as heir:
        begun = await heir.stats.begin_match(
            {"match_id": "m1", "started_at": 1790000000000}, idempotency_key="begin-m1"
        )
    assert begun.approval == "manual" and api.requests[0].headers["idempotency-key"] == "begin-m1"
