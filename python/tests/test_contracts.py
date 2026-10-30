"""All public SDK operations against the shared wire fixtures, without network access."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from heir import AsyncHeir, AsyncPage, Heir, Page

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "tests/contracts.json").read_text())["cases"]
ID = "9f6d2a70-0000-4000-8000-000000000000"
PLAYER = "A1B2C3D4E5F67890"


def invoke(client: Any, case: dict[str, Any]) -> Any:
    league = client.league("nacl")
    body = case.get("requestBody")
    calls = {
        "getLeaguePlayer": lambda: league.player("mordhau", PLAYER),
        "lookupLeaguePlayers": lambda: league.lookup_players("mordhau", [PLAYER]),
        "getLeaguePlayerStats": lambda: league.player_stats("mordhau", PLAYER),
        "getLeaguePlayerMatches": lambda: league.player_matches("mordhau", PLAYER),
        "listLeagueRosters": league.rosters,
        "getLeagueRoster": lambda: league.roster(ID),
        "getLeagueLeaderboard": league.leaderboard,
        "getLeagueStandings": league.standings,
        "listLeagueFixtures": league.fixtures,
        "getLeagueFixture": lambda: league.fixture(ID),
        "getLeagueMatch": lambda: league.match(ID),
        "getLeagueConfig": league.config,
        "checkLeagueEligibility": lambda: league.check_eligibility(
            "mordhau", [PLAYER], fixture_id=ID, roster_id=ID, gamemode="SKM"
        ),
        "getPlayerInventory": lambda: league.inventory("mordhau", PLAYER),
        "getPlayersInventory": lambda: league.inventories("mordhau", [PLAYER]),
        "getLeagueItems": league.items,
        "submitCompleteMatch": lambda: client.stats.submit_match(body),
        "listGamemodes": client.stats.gamemodes,
        "listStatSchemas": client.stats.schemas,
        "beginMatch": lambda: client.stats.begin_match(body),
        "appendUnits": lambda: client.stats.append_units(ID, body),
        "heartbeatMatch": lambda: client.stats.heartbeat(ID),
        "finalizeMatch": lambda: client.stats.finalize(ID),
        "uploadMatch": lambda: client.stats.upload(body),
    }
    return calls[case["operationId"]]()


def handler(case: dict[str, Any]) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == case["method"]
        assert str(request.url) == "https://api.heir.gg" + case["path"]
        assert request.headers["authorization"] == "Bearer test-key"
        assert (json.loads(request.content) if request.content else None) == case.get("requestBody")
        if case["operationId"] in {"beginMatch", "appendUnits", "heartbeatMatch", "finalizeMatch", "uploadMatch"}:
            assert request.headers["idempotency-key"]
        return httpx.Response(200, json=case["responseBody"])

    return respond


def assert_body(result: Any, case: dict[str, Any]) -> None:
    body = result.body if isinstance(result, (Page, AsyncPage)) else result
    assert body.model_dump(mode="json", by_alias=True, exclude_unset=True) == case["responseBody"]


def test_contract_fixtures_cover_the_openapi_operations() -> None:
    operations = {
        operation["operationId"]
        for name in ["public-openapi.json", "stat-submission-openapi.json"]
        for path in json.loads((ROOT / "spec" / name).read_text())["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    }
    assert len(CASES) == len(operations) == 24
    assert {case["operationId"] for case in CASES} == operations


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operationId"])
def test_sync_operation(case: dict[str, Any]) -> None:
    with (
        httpx.Client(transport=httpx.MockTransport(handler(case))) as http,
        Heir(api_key="test-key", http_client=http) as client,
    ):
        assert_body(invoke(client, case), case)


@pytest.mark.anyio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operationId"])
async def test_async_operation(case: dict[str, Any]) -> None:
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler(case))) as http,
        AsyncHeir(api_key="test-key", http_client=http) as client,
    ):
        assert_body(await invoke(client, case), case)
