from __future__ import annotations

import inspect
from typing import Any

import anyio
import httpx
import pytest
from pydantic import ValidationError

from heir import (
    AsyncHeir,
    Heir,
    HeirAPIError,
    HeirConnectionError,
    HeirInputError,
    HeirMatchFile,
    HeirMatchMap,
    HeirMatchPlayer,
    HeirMatchScore,
    HeirProtocolError,
    HeirTimeoutError,
    MatchTemplate,
    RequestOptions,
)
from heir._errors import parse_retry_after
from heir._league import AsyncLeague, League
from heir._transport import encode

from .fake_api import PLAYER, FakeAPI, broken, respond, slow
from .test_client import Harness

RECEIPT = {"kind": "match", "id": "id", "status": "approved", "created": True, "replayed": False, "problems": []}


def test_nested_mutated_default_stats_are_sent_without_adding_unset_fields() -> None:
    player = HeirMatchPlayer(identity="player")
    assert player.stats is not None
    player.stats["kills"] = 10
    untouched = HeirMatchPlayer(identity="other")
    document = HeirMatchFile(
        format="heir-match-v1",
        started_at="2026-10-30T12:00:00Z",
        fixture_id=None,
        maps=[HeirMatchMap(players=[player, untouched], score=HeirMatchScore(a=0, b=0, c=3))],
    )
    h = Harness(respond(200, RECEIPT))
    h.heir.stats.submit_match(document)
    sent = h.api.body(0)
    assert sent["maps"][0]["players"] == [{"identity": "player", "stats": {"kills": 10}}, {"identity": "other"}]
    assert sent["maps"][0]["score"] == {"a": 0, "b": 0, "c": 3}
    assert sent["fixtureId"] is None
    assert "endedAt" not in sent and "type" not in sent
    assert player.model_fields_set == {"identity"}, "serialization must not mutate caller models"
    assert encode(HeirMatchPlayer(stats=None)) == {"stats": None}


def test_catalog_template_can_be_submitted_directly() -> None:
    template = MatchTemplate(
        format="heir-match-v1",
        started_at="2026-10-30T12:00:00Z",
        maps=[HeirMatchMap(players=[])],
    )
    template.maps[0].players.append(HeirMatchPlayer(identity="player", stats={"kills": 3}))
    template.reference = "game-1"
    h = Harness(respond(200, RECEIPT))
    assert h.heir.stats.submit_match(template).created
    assert h.api.body(0)["maps"][0]["players"][0]["stats"] == {"kills": 3}
    assert "endedAt" not in h.api.body(0)


def test_serialization_uses_current_extra_fields_and_skips_deleted_fields() -> None:
    score = HeirMatchScore(a=0, b=0, c=3)
    del score.c
    assert encode(score) == {"a": 0, "b": 0}
    assert score.model_extra is not None
    score.model_extra["d"] = 4
    assert encode(score) == {"a": 0, "b": 0, "d": 4}
    player = HeirMatchPlayer(identity="player", name="Old name")
    del player.name
    assert encode(player) == {"identity": "player"}


def test_invalid_request_is_an_sdk_input_error_before_http() -> None:
    h = Harness()
    with pytest.raises(HeirInputError) as caught:
        h.heir.stats.begin_match({})
    assert isinstance(caught.value.__cause__, ValidationError)
    with pytest.raises(HeirInputError):
        h.heir.league("nacl").lookup_players("mordhau", [None])  # type: ignore[list-item]
    assert h.api.calls == 0


@pytest.mark.parametrize("body", ["not-json", {"wrong": "shape"}])
def test_malformed_success_is_a_protocol_error_and_is_not_cached(body: Any) -> None:
    h = Harness(respond(200, body, {"cache-control": "max-age=60"}), respond(200, PLAYER))
    with pytest.raises(HeirProtocolError) as caught:
        h.heir.league("nacl").player("mordhau", "id")
    assert caught.value.body and isinstance(caught.value.__cause__, ValidationError)
    assert h.heir.league("nacl").player("mordhau", "id").player is not None
    assert h.api.calls == 2


@pytest.mark.parametrize("issues", [["bad", None, {"path": "x", "message": "detail"}], "bad", 5, {"x": "bad"}])
def test_error_envelope_keeps_http_error_when_issues_are_malformed(issues: Any) -> None:
    h = Harness(respond(400, {"error": "invalid-request", "message": "bad", "issues": issues}))
    with pytest.raises(HeirAPIError) as caught:
        h.heir.league("nacl").config()
    assert caught.value.status_code == 400 and caught.value.body["issues"] == issues
    assert len(caught.value.issues) == (1 if isinstance(issues, list) else 0)


def test_connection_backoff_obeys_retry_delay_cap() -> None:
    h = Harness(broken, max_retry_delay=0)
    with pytest.raises(HeirConnectionError):
        h.heir.league("nacl").config()
    assert h.sleeps == [] and h.api.calls == 1


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_retry_after_is_ignored(value: str) -> None:
    assert parse_retry_after(value) is None


def test_custom_headers_bypass_cache_and_protected_headers_are_case_insensitive() -> None:
    h = Harness(*(respond(200, PLAYER, {"cache-control": "max-age=60"}) for _ in range(3)), api_key="client-key")
    league = h.heir.league("nacl")
    league.player("mordhau", "id")
    for token in ["one", "two"]:
        league.player("mordhau", "id", options=RequestOptions(headers={"authorization": "Bearer " + token}))
    assert h.api.calls == 3
    assert all(req.headers.get_list("authorization") == ["Bearer client-key"] for req in h.api.requests)
    league.player("mordhau", "id")
    assert h.api.calls == 3, "custom requests must not replace the ordinary cache entry"


def test_response_age_reduces_freshness() -> None:
    h = Harness(respond(200, PLAYER, {"cache-control": "max-age=60", "age": "55"}), respond(200, PLAYER))
    read = lambda: h.heir.league("nacl").player("mordhau", "id")  # noqa: E731
    read()
    h.clock += 4
    read()
    assert h.api.calls == 1
    h.clock += 2
    read()
    assert h.api.calls == 2


def test_response_date_limits_freshness_even_without_age() -> None:
    h = Harness(
        respond(200, PLAYER, {"cache-control": "max-age=60", "date": "Fri, 30 Oct 2026 12:00:00 GMT"}),
        respond(200, PLAYER),
    )
    h.heir._transport.wall_now = lambda: 1793361655.0
    h.heir.league("nacl").player("mordhau", "id")
    h.clock += 6
    h.heir.league("nacl").player("mordhau", "id")
    assert h.api.calls == 2


def test_unrepresentable_cache_age_does_not_break_a_successful_read() -> None:
    h = Harness(respond(200, PLAYER, {"cache-control": "max-age=" + "9" * 1000}), respond(200, PLAYER))
    for _ in range(2):
        assert h.heir.league("nacl").player("mordhau", "id").player is not None
    assert h.api.calls == 2


@pytest.mark.parametrize("segment", ["", ".", ".."])
def test_unsafe_url_segments_fail_before_http(segment: str) -> None:
    h = Harness()
    with pytest.raises(HeirInputError):
        h.heir.league(segment)
    with pytest.raises(HeirInputError):
        h.heir.league("nacl").player("mordhau", segment)
    with pytest.raises(HeirInputError):
        h.heir.stats.heartbeat(segment)
    assert h.api.calls == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"cache-control": "no-cache, max-age=60", "etag": '"v1"'},
        {"cache-control": "max-age=60", "vary": "Authorization"},
        {"cache-control": "max-age=60", "vary": "*"},
    ],
)
def test_no_cache_and_vary_are_not_served_fresh(headers: dict[str, str]) -> None:
    h = Harness(respond(200, PLAYER, headers), respond(200, PLAYER, headers))
    for _ in range(2):
        h.heir.league("nacl").player("mordhau", "id")
    assert h.api.calls == 2
    assert ("if-none-match" in h.api.requests[1].headers) == ("etag" in headers)


def test_304_preserves_policy_and_updates_etag() -> None:
    h = Harness(
        respond(200, PLAYER, {"cache-control": "max-age=60", "etag": '"v1"', "age": "59"}),
        respond(304, b"", {"etag": '"v2"'}),
        respond(304, b"", {"cache-control": "no-store"}),
        respond(200, PLAYER),
    )
    read = lambda: h.heir.league("nacl").player("mordhau", "id")  # noqa: E731
    read()
    h.clock += 2
    read()
    h.clock += 59
    read()
    assert h.api.calls == 2
    h.clock += 2
    read()
    assert h.api.requests[2].headers["if-none-match"] == '"v2"'
    read()
    assert h.api.calls == 4 and "if-none-match" not in h.api.requests[3].headers


def test_cache_evicts_one_least_recent_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("heir._transport.MAX_CACHE_ENTRIES", 2)
    h = Harness(*(respond(200, PLAYER, {"cache-control": "max-age=60"}) for _ in range(4)))
    league = h.heir.league("nacl")
    for identifier in ["a", "b", "a", "c", "a"]:
        league.player("mordhau", identifier)
    assert h.api.calls == 3
    league.player("mordhau", "b")
    assert h.api.calls == 4


@pytest.mark.parametrize(
    "options",
    [
        {"max_retries": -1},
        {"max_retries": 1.5},
        {"max_retries": True},
        {"max_retry_delay": -1},
        {"max_retry_delay": float("nan")},
        {"max_retry_delay": float("inf")},
        {"timeout": 0},
        {"timeout": -1},
        {"timeout": float("nan")},
        {"base_url": "relative"},
        {"base_url": "ftp://example.com"},
        {"base_url": "https://a:b@example.com"},
        {"base_url": "https://example.com?x=1"},
        {"base_url": "https://example.com#fragment"},
        {"base_url": "https://example.com/?"},
        {"base_url": "https://example.com/#"},
        {"cache": "yes"},
        {"api_key": 1},
        {"api_key": "bad\nkey"},
        {"user_agent": "bad\ragent"},
    ],
)
def test_invalid_configuration_fails_consistently(options: dict[str, Any]) -> None:
    for factory in [Heir, AsyncHeir]:
        with pytest.raises(HeirInputError):
            factory(**options)


def test_eligibility_signature_has_no_unsupported_category() -> None:
    assert "category" not in inspect.signature(League.check_eligibility).parameters
    assert "category" not in inspect.signature(AsyncLeague.check_eligibility).parameters


@pytest.mark.anyio
async def test_async_protocol_errors_and_retry_caps() -> None:
    api = FakeAPI(respond(200, {"wrong": "shape"}), broken)
    async with (
        httpx.AsyncClient(transport=api.transport()) as http,
        AsyncHeir(http_client=http, max_retry_delay=0) as client,
    ):
        with pytest.raises(HeirProtocolError):
            await client.league("nacl").player("mordhau", "id")
        with pytest.raises(HeirConnectionError):
            await client.league("nacl").player("mordhau", "id")
    assert api.calls == 2


@pytest.mark.anyio
async def test_cached_async_response_respects_preexisting_cancellation() -> None:
    api = FakeAPI(respond(200, PLAYER, {"cache-control": "max-age=60"}))
    async with (
        httpx.AsyncClient(transport=api.transport()) as http,
        AsyncHeir(http_client=http) as client,
    ):
        await client.league("nacl").player("mordhau", "id")
        with anyio.CancelScope() as scope:
            scope.cancel()
            await client.league("nacl").player("mordhau", "id")
            pytest.fail("a cache hit must not swallow cancellation")
        assert scope.cancelled_caught
    assert api.calls == 1


def test_injected_sync_client_does_not_report_sdk_timeout() -> None:
    api = FakeAPI(slow)
    with httpx.Client(transport=api.transport(), timeout=0.01) as http, Heir(http_client=http) as client:
        with pytest.raises(HeirTimeoutError) as caught:
            client.league("nacl").player("mordhau", "id")
        assert api.requests[0].extensions["timeout"]["read"] == 0.01
        assert caught.value.timeout is None
        assert "30" not in str(caught.value)
        assert isinstance(caught.value.__cause__, httpx.ReadTimeout)
        with pytest.raises(HeirInputError):
            Heir(http_client=http, timeout=-1)


@pytest.mark.anyio
async def test_injected_async_client_does_not_report_sdk_timeout() -> None:
    api = FakeAPI(slow)
    async with (
        httpx.AsyncClient(transport=api.transport(), timeout=0.01) as http,
        AsyncHeir(http_client=http) as client,
    ):
        with pytest.raises(HeirTimeoutError) as caught:
            await client.league("nacl").player("mordhau", "id")
        assert api.requests[0].extensions["timeout"]["read"] == 0.01
        assert caught.value.timeout is None
        assert "30" not in str(caught.value)
        assert isinstance(caught.value.__cause__, httpx.ReadTimeout)
        with pytest.raises(HeirInputError):
            AsyncHeir(http_client=http, timeout=-1)


def test_sdk_owned_client_reports_its_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(method: str, url: str, **_: Any) -> httpx.Response:
        return slow(httpx.Request(method, url))

    with Heir(timeout=1.5) as client:
        monkeypatch.setattr(client._http, "request", timeout)
        with pytest.raises(HeirTimeoutError) as caught:
            client.league("nacl").player("mordhau", "id")
        assert caught.value.timeout == 1.5
