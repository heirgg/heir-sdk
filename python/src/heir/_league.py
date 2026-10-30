"""One League's public reads, for the sync and the async client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ._errors import HeirInputError
from ._pagination import AsyncPage, Page
from ._transport import Call, RequestOptions, validate_request
from ._types import Category, FixtureStatus, Metric
from .models import (
    EligibilityRequest,
    EligibilityResponse,
    Fixture,
    FixtureResponse,
    FixturesResponse,
    InventoryBatchRequest,
    InventoryBatchResponse,
    InventoryResponse,
    LeaderboardEntry,
    LeaderboardResponse,
    LeagueConfigResponse,
    LeagueItemsResponse,
    MatchResponse,
    PlayerLookupRequest,
    PlayerLookupResponse,
    PlayerMatch,
    PlayerMatchesResponse,
    PlayerResponse,
    PlayerStatsResponse,
    Roster,
    RosterResponse,
    RostersResponse,
    Standing,
    StandingsResponse,
)

if TYPE_CHECKING:
    from ._client import AsyncHeir, Heir


def _segment(value: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise HeirInputError("URL path parameters must be non-empty strings other than '.' or '..'")
    return quote(value, safe="")


def _list_query(
    *,
    category: str | None = None,
    gamemode: str | None = None,
    page: int | None,
    page_size: int | None,
    next_token: str | None,
    **extra: str | None,
) -> dict[str, str | int | None]:
    """The parameters every list shares. `page` cannot be combined with a token."""
    return {
        "category": category,
        "gamemode": gamemode,
        **extra,
        "page": None if next_token else page,
        "pageSize": page_size,
        "nextToken": next_token,
    }


class _LeagueCalls:
    """Builds the calls; the two clients only send them."""

    #: The League as it was named: its vanity name or Discord server ID.
    ref: str

    def __init__(self, ref: str) -> None:
        self.ref = ref
        self._base = "/public/v1/leagues/" + _segment(ref)

    def _get(self, path: str, query: dict[str, str | int | None] | None = None) -> Call:
        return Call("GET", self._base + path, query=query, idempotent=True, cacheable=True)

    def _post(self, path: str, body: Any) -> Call:
        # These POSTs read and never write, so they are safe to send again; the API does not cache them.
        return Call("POST", self._base + path, body=body, idempotent=True, cacheable=False)

    def _players(self, credential: str, identifier: str, tail: str = "") -> str:
        return f"/players/{_segment(credential)}/{_segment(identifier)}{tail}"


class League(_LeagueCalls):
    """One League's public reads: players, ratings, Rosters, schedules, results and shop inventory.

    Reads need no key and are cached for a minute as the API asks; with the League's own developer key they draw on
    the plan's allowance instead of the per-address limit. Get one from ``Heir.league("nacl")``, by vanity name or
    Discord server ID.
    """

    def __init__(self, client: Heir, ref: str) -> None:
        super().__init__(ref)
        self._client = client

    def player(
        self,
        credential: str,
        identifier: str,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        options: RequestOptions | None = None,
    ) -> PlayerResponse:
        """One current Member by linked game account, for nameplates and player cards. ``player`` is None for an unknown
        or departed identity.
        """
        return self._client._send(
            self._get(self._players(credential, identifier), {"category": category, "gamemode": gamemode}),
            PlayerResponse,
            options,
        )

    def lookup_players(
        self,
        credential: str,
        identifiers: list[str],
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        options: RequestOptions | None = None,
    ) -> PlayerLookupResponse:
        """Up to 100 game accounts at once, each answered in order, including duplicates and unavailable identities."""
        request = validate_request(
            PlayerLookupRequest,
            dict(credential=credential, identifiers=identifiers, **_set(category=category, gamemode=gamemode)),
        )
        return self._client._send(self._post("/players/lookup", request), PlayerLookupResponse, options)

    def player_stats(
        self,
        credential: str,
        identifier: str,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        options: RequestOptions | None = None,
    ) -> PlayerStatsResponse:
        """The Player's League win/loss record and stored performance totals for the scope."""
        return self._client._send(
            self._get(self._players(credential, identifier, "/stats"), {"category": category, "gamemode": gamemode}),
            PlayerStatsResponse,
            options,
        )

    def player_matches(
        self,
        credential: str,
        identifier: str,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> Page[PlayerMatch, PlayerMatchesResponse]:
        """The Player's rated results and MMR changes, newest first."""
        body = self._client._send(
            self._get(
                self._players(credential, identifier, "/matches"),
                _list_query(
                    category=category, gamemode=gamemode, page=page, page_size=page_size, next_token=next_token
                ),
            ),
            PlayerMatchesResponse,
            options,
        )
        return Page(
            body,
            body.matches,
            body.has_more,
            body.next_token,
            lambda token: self.player_matches(
                credential,
                identifier,
                category=category,
                gamemode=gamemode,
                page_size=page_size,
                next_token=token,
                options=options,
            ),
        )

    def rosters(
        self,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> Page[Roster, RostersResponse]:
        """Active Rosters with their Team tags, logos, captain and Team MMR."""
        body = self._client._send(
            self._get(
                "/rosters",
                _list_query(
                    category=category, gamemode=gamemode, page=page, page_size=page_size, next_token=next_token
                ),
            ),
            RostersResponse,
            options,
        )
        return Page(
            body,
            body.rosters,
            body.has_more,
            body.next_token,
            lambda token: self.rosters(
                category=category, gamemode=gamemode, page_size=page_size, next_token=token, options=options
            ),
        )

    def roster(
        self,
        id: str,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        options: RequestOptions | None = None,
    ) -> RosterResponse:
        """One active Roster and its seated Members."""
        return self._client._send(
            self._get(f"/rosters/{_segment(id)}", {"category": category, "gamemode": gamemode}), RosterResponse, options
        )

    def leaderboard(
        self,
        *,
        metric: Metric | None = None,
        category: Category | None = None,
        gamemode: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> Page[LeaderboardEntry, LeaderboardResponse]:
        """Current Members ordered by MMR, Heir Rating, wins or losses.

        A five-minute snapshot; ``body.snapshot_at`` says which.
        """
        body = self._client._send(
            self._get(
                "/leaderboards",
                _list_query(
                    category=category,
                    gamemode=gamemode,
                    metric=metric,
                    page=page,
                    page_size=page_size,
                    next_token=next_token,
                ),
            ),
            LeaderboardResponse,
            options,
        )
        return Page(
            body,
            body.entries,
            body.has_more,
            body.next_token,
            lambda token: self.leaderboard(
                metric=metric,
                category=category,
                gamemode=gamemode,
                page_size=page_size,
                next_token=token,
                options=options,
            ),
        )

    def standings(
        self,
        *,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> Page[Standing, StandingsResponse]:
        """Current-season Roster standings in competition order."""
        body = self._client._send(
            self._get("/standings", _list_query(page=page, page_size=page_size, next_token=next_token)),
            StandingsResponse,
            options,
        )
        return Page(
            body,
            body.standings,
            body.has_more,
            body.next_token,
            lambda token: self.standings(page_size=page_size, next_token=token, options=options),
        )

    def fixtures(
        self,
        *,
        status: FixtureStatus | None = None,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> Page[Fixture, FixturesResponse]:
        """Fixtures in scheduled-time order: scheduled by default, or played or cancelled with ``status``."""
        body = self._client._send(
            self._get("/fixtures", _list_query(status=status, page=page, page_size=page_size, next_token=next_token)),
            FixturesResponse,
            options,
        )
        return Page(
            body,
            body.fixtures,
            body.has_more,
            body.next_token,
            lambda token: self.fixtures(status=status, page_size=page_size, next_token=token, options=options),
        )

    def fixture(self, id: str, *, options: RequestOptions | None = None) -> FixtureResponse:
        """One fixture: its Rosters, time, status, stream link and recorded result."""
        return self._client._send(self._get(f"/fixtures/{_segment(id)}"), FixtureResponse, options)

    def match(self, id: str, *, options: RequestOptions | None = None) -> MatchResponse:
        """An official result or approved recording by UUID."""
        return self._client._send(self._get(f"/matches/{_segment(id)}"), MatchResponse, options)

    def config(self, *, options: RequestOptions | None = None) -> LeagueConfigResponse:
        """Game credentials, active gamemodes, rating categories, rank definitions and batch limits."""
        return self._client._send(self._get("/config"), LeagueConfigResponse, options)

    def check_eligibility(
        self,
        credential: str,
        identifiers: list[str],
        *,
        fixture_id: str,
        roster_id: str,
        gamemode: str,
        options: RequestOptions | None = None,
    ) -> EligibilityResponse:
        """Check up to 100 game accounts against a fixture and one of its Rosters.

        Requires the League's developer key with the gamemode granted. Advisory: it reserves no seats. Call it from
        your server.
        """
        request = validate_request(
            EligibilityRequest,
            dict(
                credential=credential,
                identifiers=identifiers,
                fixture_id=fixture_id,
                roster_id=roster_id,
                gamemode=gamemode,
            ),
        )
        return self._client._send(self._post("/eligibility/check", request), EligibilityResponse, options)

    def inventory(
        self, credential: str, identifier: str, *, item: str | None = None, options: RequestOptions | None = None
    ) -> InventoryResponse:
        """The items one game account's owner holds in the League's shop right now. An empty list is a normal answer."""
        return self._client._send(
            self._get(f"/inventory/{_segment(credential)}/{_segment(identifier)}", {"item": item}),
            InventoryResponse,
            options,
        )

    def inventories(
        self, credential: str, identifiers: list[str], *, item: str | None = None, options: RequestOptions | None = None
    ) -> InventoryBatchResponse:
        """The same for up to 100 game accounts at once, such as everyone on a server. Not cached."""
        request = validate_request(InventoryBatchRequest, dict(identifiers=identifiers, **_set(item=item)))
        return self._client._send(
            self._post(f"/inventory/{_segment(credential)}", request), InventoryBatchResponse, options
        )

    def items(self, *, options: RequestOptions | None = None) -> LeagueItemsResponse:
        """Every item the League's shop knows, and the kinds of game account its inventory calls accept."""
        return self._client._send(self._get("/items"), LeagueItemsResponse, options)


class AsyncLeague(_LeagueCalls):
    """One League's public reads, from an ``AsyncHeir``. See ``League`` for what each read answers."""

    def __init__(self, client: AsyncHeir, ref: str) -> None:
        super().__init__(ref)
        self._client = client

    async def player(
        self,
        credential: str,
        identifier: str,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        options: RequestOptions | None = None,
    ) -> PlayerResponse:
        return await self._client._send(
            self._get(self._players(credential, identifier), {"category": category, "gamemode": gamemode}),
            PlayerResponse,
            options,
        )

    async def lookup_players(
        self,
        credential: str,
        identifiers: list[str],
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        options: RequestOptions | None = None,
    ) -> PlayerLookupResponse:
        request = validate_request(
            PlayerLookupRequest,
            dict(credential=credential, identifiers=identifiers, **_set(category=category, gamemode=gamemode)),
        )
        return await self._client._send(self._post("/players/lookup", request), PlayerLookupResponse, options)

    async def player_stats(
        self,
        credential: str,
        identifier: str,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        options: RequestOptions | None = None,
    ) -> PlayerStatsResponse:
        return await self._client._send(
            self._get(self._players(credential, identifier, "/stats"), {"category": category, "gamemode": gamemode}),
            PlayerStatsResponse,
            options,
        )

    async def player_matches(
        self,
        credential: str,
        identifier: str,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> AsyncPage[PlayerMatch, PlayerMatchesResponse]:
        body = await self._client._send(
            self._get(
                self._players(credential, identifier, "/matches"),
                _list_query(
                    category=category, gamemode=gamemode, page=page, page_size=page_size, next_token=next_token
                ),
            ),
            PlayerMatchesResponse,
            options,
        )
        return AsyncPage(
            body,
            body.matches,
            body.has_more,
            body.next_token,
            lambda token: self.player_matches(
                credential,
                identifier,
                category=category,
                gamemode=gamemode,
                page_size=page_size,
                next_token=token,
                options=options,
            ),
        )

    async def rosters(
        self,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> AsyncPage[Roster, RostersResponse]:
        body = await self._client._send(
            self._get(
                "/rosters",
                _list_query(
                    category=category, gamemode=gamemode, page=page, page_size=page_size, next_token=next_token
                ),
            ),
            RostersResponse,
            options,
        )
        return AsyncPage(
            body,
            body.rosters,
            body.has_more,
            body.next_token,
            lambda token: self.rosters(
                category=category, gamemode=gamemode, page_size=page_size, next_token=token, options=options
            ),
        )

    async def roster(
        self,
        id: str,
        *,
        category: Category | None = None,
        gamemode: str | None = None,
        options: RequestOptions | None = None,
    ) -> RosterResponse:
        return await self._client._send(
            self._get(f"/rosters/{_segment(id)}", {"category": category, "gamemode": gamemode}), RosterResponse, options
        )

    async def leaderboard(
        self,
        *,
        metric: Metric | None = None,
        category: Category | None = None,
        gamemode: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> AsyncPage[LeaderboardEntry, LeaderboardResponse]:
        body = await self._client._send(
            self._get(
                "/leaderboards",
                _list_query(
                    category=category,
                    gamemode=gamemode,
                    metric=metric,
                    page=page,
                    page_size=page_size,
                    next_token=next_token,
                ),
            ),
            LeaderboardResponse,
            options,
        )
        return AsyncPage(
            body,
            body.entries,
            body.has_more,
            body.next_token,
            lambda token: self.leaderboard(
                metric=metric,
                category=category,
                gamemode=gamemode,
                page_size=page_size,
                next_token=token,
                options=options,
            ),
        )

    async def standings(
        self,
        *,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> AsyncPage[Standing, StandingsResponse]:
        body = await self._client._send(
            self._get("/standings", _list_query(page=page, page_size=page_size, next_token=next_token)),
            StandingsResponse,
            options,
        )
        return AsyncPage(
            body,
            body.standings,
            body.has_more,
            body.next_token,
            lambda token: self.standings(page_size=page_size, next_token=token, options=options),
        )

    async def fixtures(
        self,
        *,
        status: FixtureStatus | None = None,
        page: int | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
        options: RequestOptions | None = None,
    ) -> AsyncPage[Fixture, FixturesResponse]:
        body = await self._client._send(
            self._get("/fixtures", _list_query(status=status, page=page, page_size=page_size, next_token=next_token)),
            FixturesResponse,
            options,
        )
        return AsyncPage(
            body,
            body.fixtures,
            body.has_more,
            body.next_token,
            lambda token: self.fixtures(status=status, page_size=page_size, next_token=token, options=options),
        )

    async def fixture(self, id: str, *, options: RequestOptions | None = None) -> FixtureResponse:
        return await self._client._send(self._get(f"/fixtures/{_segment(id)}"), FixtureResponse, options)

    async def match(self, id: str, *, options: RequestOptions | None = None) -> MatchResponse:
        return await self._client._send(self._get(f"/matches/{_segment(id)}"), MatchResponse, options)

    async def config(self, *, options: RequestOptions | None = None) -> LeagueConfigResponse:
        return await self._client._send(self._get("/config"), LeagueConfigResponse, options)

    async def check_eligibility(
        self,
        credential: str,
        identifiers: list[str],
        *,
        fixture_id: str,
        roster_id: str,
        gamemode: str,
        options: RequestOptions | None = None,
    ) -> EligibilityResponse:
        request = validate_request(
            EligibilityRequest,
            dict(
                credential=credential,
                identifiers=identifiers,
                fixture_id=fixture_id,
                roster_id=roster_id,
                gamemode=gamemode,
            ),
        )
        return await self._client._send(self._post("/eligibility/check", request), EligibilityResponse, options)

    async def inventory(
        self, credential: str, identifier: str, *, item: str | None = None, options: RequestOptions | None = None
    ) -> InventoryResponse:
        return await self._client._send(
            self._get(f"/inventory/{_segment(credential)}/{_segment(identifier)}", {"item": item}),
            InventoryResponse,
            options,
        )

    async def inventories(
        self, credential: str, identifiers: list[str], *, item: str | None = None, options: RequestOptions | None = None
    ) -> InventoryBatchResponse:
        request = validate_request(InventoryBatchRequest, dict(identifiers=identifiers, **_set(item=item)))
        return await self._client._send(
            self._post(f"/inventory/{_segment(credential)}", request), InventoryBatchResponse, options
        )

    async def items(self, *, options: RequestOptions | None = None) -> LeagueItemsResponse:
        return await self._client._send(self._get("/items"), LeagueItemsResponse, options)


def _set(**values: Any) -> dict[str, Any]:
    """Only the keyword arguments that were given, so a model field left out stays unset and is not sent."""
    return {name: value for name, value in values.items() if value is not None}
