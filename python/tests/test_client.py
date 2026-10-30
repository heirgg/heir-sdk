from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from heir import (
    Heir,
    HeirAPIError,
    HeirConnectionError,
    HeirMatchFile,
    HeirMatchMap,
    HeirMatchPlayer,
    HeirTimeoutError,
    RequestOptions,
    __version__,
    new_idempotency_key,
)
from heir._errors import parse_retry_after

from .fake_api import PLAYER, FakeAPI, api_error, broken, respond, roster, slow

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class Harness:
    """A client over a fake API whose sleeps are recorded instead of taken, and whose clock is a variable."""

    def __init__(self, *steps, **options) -> None:  # type: ignore[no-untyped-def]
        self.api = FakeAPI(*steps)
        self.heir = Heir(http_client=httpx.Client(transport=self.api.transport()), **options)
        self.sleeps: list[float] = []
        self.heir._sleep = self.sleeps.append
        self.clock = 1_000_000.0
        self.heir._transport.now = lambda: self.clock


def test_request_builds_url_and_headers() -> None:
    h = Harness(respond(200, PLAYER), api_key="key-1", user_agent="my-server/2.0")
    answer = h.heir.league("nacl").player("mordhau", "A1B2C3D4E5F67890", category="competitive", gamemode=None)
    assert answer.player is not None and answer.player.display_name == "Ada"
    request = h.api.requests[0]
    assert (
        str(request.url)
        == "https://api.heir.gg/public/v1/leagues/nacl/players/mordhau/A1B2C3D4E5F67890?category=competitive"
    )
    assert request.headers["authorization"] == "Bearer key-1"
    assert request.headers["accept"] == "application/json"
    assert request.headers["user-agent"] == f"heir-sdk-python/{__version__} my-server/2.0"
    assert h.heir.authenticated


def test_keyless_reads_and_escaping() -> None:
    h = Harness(
        respond(
            200,
            {
                "fixture": {
                    "id": "x",
                    "code": None,
                    "rosterA": {"id": "a", "name": "A"},
                    "rosterB": {"id": "b", "name": "B"},
                    "scheduledAt": None,
                    "status": "scheduled",
                    "resultMatchId": None,
                    "scoreA": None,
                    "scoreB": None,
                    "streamUrl": None,
                }
            },
        ),
        base_url="https://staging.example.test/",
    )
    h.heir.league("123456789012345678").fixture("a/b c")
    request = h.api.requests[0]
    assert str(request.url) == "https://staging.example.test/public/v1/leagues/123456789012345678/fixtures/a%2Fb%20c"
    assert "authorization" not in request.headers
    assert not h.heir.authenticated


def test_posts_json_for_lookup_reads_in_the_api_spelling() -> None:
    h = Harness(respond(200, {"players": []}))
    h.heir.league("nacl").lookup_players("steam", ["76561198000000000"])
    request = h.api.requests[0]
    assert request.method == "POST" and request.headers["content-type"] == "application/json"
    assert h.api.body(0) == {"credential": "steam", "identifiers": ["76561198000000000"]}
    h.api.steps = [respond(200, {"fixtureId": "f", "rosterId": "r", "checkedAt": "now", "players": []})]
    h.heir.league("nacl").check_eligibility(
        "mordhau", ["A1B2C3D4E5F67890"], fixture_id="f", roster_id="r", gamemode="SKM"
    )
    assert h.api.body(1) == {
        "credential": "mordhau",
        "identifiers": ["A1B2C3D4E5F67890"],
        "fixtureId": "f",
        "rosterId": "r",
        "gamemode": "SKM",
    }


def test_api_error_envelope() -> None:
    h = Harness(
        respond(
            400,
            {
                "error": "invalid-request",
                "message": "The match could not be read.",
                "issues": [{"path": "maps.0.winner", "message": "Invalid option"}],
            },
        ),
        api_key="k",
    )
    with pytest.raises(HeirAPIError) as caught:
        h.heir.stats.submit_match(
            {"format": "heir-match-v1", "startedAt": "2026-10-16T19:00:00Z", "maps": [{"players": [{"identity": "x"}]}]}
        )
    error = caught.value
    assert (error.status_code, error.code, error.message) == (400, "invalid-request", "The match could not be read.")
    assert error.issues[0].path == "maps.0.winner" and not error.is_rate_limited
    assert str(error) == "invalid-request (400): The match could not be read."
    assert h.api.calls == 1


def test_an_answer_that_is_not_the_envelope_is_still_an_api_error_and_a_read_is_retried() -> None:
    gateway = respond(502, "<html>bad gateway</html>")
    h = Harness(gateway, gateway, gateway)
    with pytest.raises(HeirAPIError) as caught:
        h.heir.league("nacl").config()
    assert (caught.value.status_code, caught.value.code, caught.value.body) == (
        502,
        "unknown",
        "<html>bad gateway</html>",
    )
    assert h.api.calls == 3 and len(h.sleeps) == 2


def test_connection_failure_is_retried_for_a_read() -> None:
    h = Harness(broken, respond(200, {"items": [], "credentials": []}))
    assert h.heir.league("nacl").items().items == []
    assert h.api.calls == 2


def test_connection_failure_is_not_retried_for_a_submission_without_reference() -> None:
    h = Harness(broken, api_key="k")
    with pytest.raises(HeirConnectionError) as caught:
        h.heir.stats.submit_match(
            HeirMatchFile(
                format="heir-match-v1",
                started_at=datetime.now(timezone.utc),
                maps=[HeirMatchMap(players=[HeirMatchPlayer(identity="x")])],
            )
        )
    assert isinstance(caught.value.__cause__, httpx.ConnectError) and not isinstance(caught.value, HeirTimeoutError)
    assert h.api.calls == 1


def test_timeout_of_one_attempt_is_not_retried() -> None:
    h = Harness(slow, slow, timeout=1.5)
    with pytest.raises(HeirTimeoutError) as caught:
        h.heir.league("nacl").config()
    assert caught.value.timeout is None and h.api.calls == 1


def test_retry_after_is_waited_for() -> None:
    h = Harness(api_error(429, "rate-limited", "Slow down.", {"retry-after": "2"}), respond(200, PLAYER))
    h.heir.league("nacl").player("mordhau", "A1B2C3D4E5F67890")
    assert h.api.calls == 2 and h.sleeps == [2.0]


def test_retry_after_beyond_the_limit_fails_at_once() -> None:
    h = Harness(api_error(429, "rate-limited", "Try again in a minute.", {"retry-after": "60"}), max_retry_delay=30)
    with pytest.raises(HeirAPIError) as caught:
        h.heir.league("nacl").config()
    assert caught.value.is_rate_limited and caught.value.retry_after == 60
    assert h.api.calls == 1 and h.sleeps == []


def test_retries_stop_at_max_and_skip_other_client_errors() -> None:
    down = api_error(503, "unavailable")
    h = Harness(down, down, down, down, max_retries=2)
    with pytest.raises(HeirAPIError) as caught:
        h.heir.league("nacl").config()
    assert caught.value.status_code == 503 and h.api.calls == 3
    once = Harness(api_error(404, "league-not-found"))
    with pytest.raises(HeirAPIError) as caught:
        once.heir.league("nope").config()
    assert caught.value.code == "league-not-found" and once.api.calls == 1


def test_cache_serves_fresh_answers_then_revalidates() -> None:
    item = {"key": "gold", "name": "Gold", "expiresAt": None, "edition": None, "imageUrl": None}

    def revalidate(request: httpx.Request) -> httpx.Response:
        assert request.headers["if-none-match"] == '"v1"'
        return httpx.Response(304, headers={"cache-control": "public, max-age=60"}, request=request)

    h = Harness(
        respond(200, {"items": [item]}, {"etag": '"v1"', "cache-control": "public, max-age=60"}),
        revalidate,
        respond(200, {"items": []}, {"etag": '"v2"', "cache-control": "public, max-age=60"}),
    )
    league = h.heir.league("nacl")
    read = lambda: len(league.inventory("mordhau", "A1B2C3D4E5F67890").items)  # noqa: E731
    assert read() == 1 and read() == 1 and h.api.calls == 1
    h.clock += 61
    assert read() == 1 and h.api.calls == 2
    assert read() == 1 and h.api.calls == 2, "a 304 makes the answer fresh again"
    h.heir.clear_cache()
    assert read() == 0 and h.api.calls == 3


def test_cache_skips_no_store_and_respects_opt_outs() -> None:
    page = {"rosters": [], "page": 0, "pageSize": 25, "hasMore": False, "nextToken": None}
    h = Harness(
        respond(200, page, {"cache-control": "no-store", "etag": '"x"'}),
        respond(200, page, {"cache-control": "no-store", "etag": '"x"'}),
    )
    h.heir.league("nacl").rosters()
    h.heir.league("nacl").rosters()
    assert h.api.calls == 2
    fresh = respond(200, {"items": [], "credentials": []}, {"cache-control": "max-age=60"})
    off = Harness(fresh, fresh, cache=False)
    off.heir.league("nacl").items()
    off.heir.league("nacl").items()
    assert off.api.calls == 2
    per_call = Harness(fresh, fresh)
    per_call.heir.league("nacl").items(options=RequestOptions(no_cache=True))
    per_call.heir.league("nacl").items(options=RequestOptions(no_cache=True))
    assert per_call.api.calls == 2


def test_cache_keeps_keyed_and_keyless_answers_apart() -> None:
    api = FakeAPI(
        respond(
            200,
            {
                "items": [{"key": "a", "name": "", "description": "", "lasts": "permanent", "imageUrl": None}],
                "credentials": [],
            },
            {"cache-control": "max-age=60"},
        ),
        respond(200, {"items": [], "credentials": []}, {"cache-control": "max-age=60"}),
    )
    anon = Heir(http_client=httpx.Client(transport=api.transport()))
    keyed = Heir(http_client=httpx.Client(transport=api.transport()), api_key="k")
    assert len(anon.league("nacl").items().items) == 1
    assert len(keyed.league("nacl").items().items) == 0


def test_pagination_walks_every_page_with_the_same_filters() -> None:
    h = Harness(
        respond(
            200, {"rosters": [roster("a"), roster("b")], "page": 0, "pageSize": 2, "hasMore": True, "nextToken": "t1"}
        ),
        respond(200, {"rosters": [roster("c")], "page": 1, "pageSize": 2, "hasMore": True, "nextToken": "t2"}),
        respond(200, {"rosters": [], "page": 2, "pageSize": 2, "hasMore": False, "nextToken": None}),
    )
    first = h.heir.league("nacl").rosters(category="competitive", page_size=2)
    assert (
        [r.name for r in first.items] == ["a", "b"]
        and first.has_more
        and first.next_token == "t1"
        and first.body.page == 0
    )
    assert [r.name for r in first] == ["a", "b", "c"]
    assert [str(r.url.query, "ascii") for r in h.api.requests] == [
        "category=competitive&pageSize=2",
        "category=competitive&pageSize=2&nextToken=t1",
        "category=competitive&pageSize=2&nextToken=t2",
    ]
    h.api.steps = [
        respond(200, {"rosters": [roster("c")], "page": 1, "pageSize": 2, "hasMore": True, "nextToken": "t2"}),
        respond(200, {"rosters": [], "page": 2, "pageSize": 2, "hasMore": False, "nextToken": None}),
    ]
    second = first.next()
    assert second is not None and len(second.items) == 1
    last = second.next()
    assert last is not None and not last.has_more and last.next() is None


def test_leaderboard_body_carries_the_snapshot() -> None:
    h = Harness(
        respond(
            200,
            {
                "metric": "mmr",
                "category": "overall",
                "entries": [
                    {"position": 1, "displayName": "Ada", "profileUrl": None, "value": 1800, "provisional": False}
                ],
                "page": 0,
                "pageSize": 25,
                "hasMore": False,
                "nextToken": None,
                "snapshotAt": "2026-10-29T10:00:00.000Z",
                "snapshotExpiresAt": "2026-10-29T10:05:00.000Z",
            },
        )
    )
    page = h.heir.league("nacl").leaderboard(metric="mmr")
    assert page.items[0].display_name == "Ada" and page.body.snapshot_at.hour == 10
    assert str(h.api.requests[0].url.query, "ascii") == "metric=mmr"


def test_tracking_writes_carry_idempotency_keys_and_dry_run() -> None:
    h = Harness(
        respond(200, {"matchId": "m1", "created": True, "approval": "automatic", "replayed": False}),
        respond(200, {"accepted": 1, "duplicates": 0, "dryRun": True}),
        respond(200, {"closed": True, "status": "approved", "heldForReview": False, "replayed": False}),
        api_key="k",
    )
    begun = h.heir.stats.begin_match({"match_id": "m1", "started_at": 1790000000000})
    assert begun.approval == "automatic" and h.api.body(0) == {"matchId": "m1", "startedAt": 1790000000000}
    appended = h.heir.stats.append_units(
        "m1",
        {"games": [{"schemaRef": "mordhau.skirmish@1", "gameId": "g1"}]},
        idempotency_key="g1-round-0",
        dry_run=True,
    )
    assert appended.dry_run is True
    h.heir.stats.finalize("m1")
    begin, append, finalize = h.api.requests
    assert UUID.match(begin.headers["idempotency-key"])
    assert append.headers["idempotency-key"] == "g1-round-0"
    assert str(append.url) == "https://api.heir.gg/public/v1/stats/matches/m1/units?dryRun=true"
    assert str(finalize.url) == "https://api.heir.gg/public/v1/stats/matches/m1/finalize"
    assert finalize.content == b"{}" and finalize.headers["content-type"] == "application/json"


def test_tracking_write_retries_with_the_same_key() -> None:
    h = Harness(broken, respond(200, {"deadline": 1, "replayed": False}), api_key="k")
    h.heir.stats.heartbeat("m1")
    keys = [r.headers["idempotency-key"] for r in h.api.requests]
    assert keys[0] and keys[0] == keys[1]


def test_submission_with_a_reference_is_retried_and_datetimes_are_sent_at_millisecond_precision() -> None:
    h = Harness(
        broken,
        respond(
            200,
            {
                "kind": "match",
                "id": "9f6d2a70-0000-4000-8000-000000000000",
                "status": "approved",
                "created": True,
                "replayed": False,
                "problems": [],
            },
        ),
        api_key="k",
    )
    file = HeirMatchFile(
        format="heir-match-v1",
        reference="lobby-42",
        started_at=datetime(2026, 10, 16, 19, 0, 0, 123456, tzinfo=timezone.utc),
        maps=[HeirMatchMap(players=[HeirMatchPlayer(identity="A1B2C3D4E5F67890", side="a", stats={"kills": 3})])],
    )
    receipt = h.heir.stats.submit_match(file)
    assert receipt.created and receipt.status == "approved" and h.api.calls == 2
    sent = h.api.body(1)
    assert sent["startedAt"] == "2026-10-16T19:00:00.123Z" and sent["reference"] == "lobby-42"
    assert sent["maps"][0]["players"][0] == {"identity": "A1B2C3D4E5F67890", "side": "a", "stats": {"kills": 3}}
    assert "type" not in sent, "a field left at its default is not sent"


def test_new_idempotency_key_is_a_uuid() -> None:
    a, b = new_idempotency_key(), new_idempotency_key()
    assert UUID.match(a) and a != b


def test_parse_retry_after() -> None:
    assert parse_retry_after(None) is None and parse_retry_after("2") == 2.0 and parse_retry_after("-1") == 0.0
    assert parse_retry_after("Thu, 01 Jan 2099 00:00:00 GMT") > 1_000_000
    assert parse_retry_after("garbage") is None


def test_query_literals_match_the_spec() -> None:
    import typing

    from heir import Category, FixtureStatus, Metric

    spec = json.loads((Path(__file__).parent.parent.parent / "spec" / "public-openapi.json").read_text())

    def enum(path: str, name: str) -> list[str]:
        return next(p["schema"]["enum"] for p in spec["paths"][path]["get"]["parameters"] if p["name"] == name)

    assert list(typing.get_args(Metric)) == enum("/public/v1/leagues/{league}/leaderboards", "metric")
    assert list(typing.get_args(FixtureStatus)) == enum("/public/v1/leagues/{league}/fixtures", "status")
    assert list(typing.get_args(Category)) == enum("/public/v1/leagues/{league}/leaderboards", "category")


def test_version_matches_pyproject() -> None:
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    found = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert found is not None and found.group(1) == __version__
