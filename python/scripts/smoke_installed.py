"""Verify an installed wheel's public imports and offline HTTP behavior.

Run this script with the interpreter from a fresh environment after installing dist/*.whl. It rejects editable
installs and uses only httpx.MockTransport; it never calls the Heir API.
"""

from __future__ import annotations

import asyncio
import json
from importlib.metadata import distribution
from pathlib import Path

import httpx

from heir import (
    AsyncHeir,
    Heir,
    HeirInputError,
    HeirMatchFile,
    HeirMatchMap,
    HeirMatchPlayer,
    HeirProtocolError,
    __version__,
)


def respond(request: httpx.Request) -> httpx.Response:
    assert request.headers["user-agent"].startswith("heir-sdk-python/")
    if request.url.path == "/public/v1/stats/matches/complete":
        body = json.loads(request.content)
        assert body["maps"][0]["players"][0] == {"identity": "player", "stats": {"kills": 3}}
        assert body["fixtureId"] is None and "endedAt" not in body
        return httpx.Response(
            200,
            json={
                "kind": "match",
                "id": "id",
                "status": "approved",
                "created": True,
                "replayed": False,
                "problems": [],
            },
        )
    assert request.url.path == "/public/v1/leagues/nacl/players/mordhau/player"
    return httpx.Response(200, json={"player": None})


async def async_check() -> None:
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http,
        AsyncHeir(http_client=http) as client,
    ):
        assert (await client.league("nacl").player("mordhau", "player")).player is None


def main() -> None:
    installed = distribution("heir-sdk")
    direct = json.loads(installed.read_text("direct_url.json") or "{}")
    assert not direct.get("dir_info", {}).get("editable"), "Use a built wheel, not an editable install"
    assert installed.version == __version__
    assert Path(str(installed.locate_file("heir/py.typed"))).is_file()
    assert HeirMatchFile.__module__ == "heir.models.stats"
    assert issubclass(HeirInputError, Exception) and issubclass(HeirProtocolError, Exception)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http, Heir(http_client=http) as client:
        assert client.league("nacl").player("mordhau", "player").player is None
        player = HeirMatchPlayer(identity="player")
        assert player.stats is not None
        player.stats["kills"] = 3
        document = HeirMatchFile(
            format="heir-match-v1",
            started_at="2026-10-30T12:00:00Z",
            fixture_id=None,
            maps=[HeirMatchMap(players=[player])],
        )
        assert client.stats.submit_match(document).created
    asyncio.run(async_check())
    print(f"Installed heir-sdk {__version__}: public imports, typing marker and sync/async HTTP checks passed")


if __name__ == "__main__":
    main()
