"""Stat submission, for the sync and the async client."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from ._transport import Call, RequestOptions
from .models import (
    AppendUnitsRequest,
    AppendUnitsResponse,
    BeginMatchRequest,
    BeginMatchResponse,
    FinalizeMatchResponse,
    GamemodeCatalog,
    HeartbeatMatchResponse,
    HeirMatchFile,
    MatchEntryReceipt,
    StatSchemaCatalog,
    UploadMatchRequest,
    UploadMatchResponse,
)

if TYPE_CHECKING:
    from ._client import AsyncHeir, Heir

_BASE = "/public/v1/stats"
ModelT = TypeVar("ModelT", bound=BaseModel)


def new_idempotency_key() -> str:
    """A fresh idempotency key: a version 4 UUID."""
    return str(uuid.uuid4())


def _as(model: type[ModelT], value: ModelT | Mapping[str, Any]) -> ModelT:
    """A request as its model, whether it came as one or as a dict in either spelling of its fields."""
    return value if isinstance(value, model) else model.model_validate(value)


def _match_path(match_id: str, tail: str) -> str:
    from urllib.parse import quote

    return f"{_BASE}/matches/{quote(match_id, safe='')}{tail}"


class _StatsCalls:
    def _read(self, path: str) -> Call:
        return Call("GET", _BASE + path, idempotent=True)

    def _submit(self, file: HeirMatchFile) -> Call:
        # With a reference, a repeat is a no-op, so the call may be sent again after a connection failure.
        return Call("POST", _BASE + "/matches/complete", body=file, idempotent=file.reference is not None)

    def _write(self, path: str, body: Any, idempotency_key: str | None, dry_run: bool) -> Call:
        return Call(
            "POST",
            path,
            query={"dryRun": "true"} if dry_run else None,
            body=body if body is not None else {},
            idempotent=True,
            idempotency_key=idempotency_key or new_idempotency_key(),
        )


class Stats(_StatsCalls):
    """Stat submission: send your game's stats to a League, for any gamemode it plays.

    Every call needs an API key with the gamemode granted. It is available while the League's stat submission API
    is switched on; otherwise the API answers 503 ``not-available``.

    Every tracking write carries an ``Idempotency-Key``. The client generates one per call, so its own retries never
    write twice; pass ``idempotency_key`` when your code may send the same request again later, so the API answers
    as it did the first time. ``dry_run=True`` checks a request without storing anything.
    """

    def __init__(self, client: Heir) -> None:
        self._client = client

    def gamemodes(self, *, options: RequestOptions | None = None) -> GamemodeCatalog:
        """The gamemodes this key may submit, built-in and custom.

        Each comes with the stat keys a Player line may carry, and an empty heir-match-v1 document to fill in.
        """
        return self._client._send(self._read("/gamemodes"), GamemodeCatalog, options)

    def schemas(self, *, options: RequestOptions | None = None) -> StatSchemaCatalog:
        """The gamemode schemas this key may track a match under, with every counter and what one unit is, and the key's
        allowances.
        """
        return self._client._send(self._read("/schemas"), StatSchemaCatalog, options)

    def submit_match(
        self, file: HeirMatchFile | Mapping[str, Any], *, options: RequestOptions | None = None
    ) -> MatchEntryReceipt:
        """One finished match as a heir-match-v1 document, for any gamemode.

        Set ``reference`` to your own id for the match: a repeat with the same contents is a no-op, and the client
        may then safely send it again after a connection failure.
        """
        return self._client._send(self._submit(_as(HeirMatchFile, file)), MatchEntryReceipt, options)

    def begin_match(
        self,
        request: BeginMatchRequest | Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
        dry_run: bool = False,
        options: RequestOptions | None = None,
    ) -> BeginMatchResponse:
        """Open a live match. It takes one of the League's live sessions until finalized or silent for 30 minutes.
        Beginning it again returns it.
        """
        return self._client._send(
            self._write(_BASE + "/matches", _as(BeginMatchRequest, request), idempotency_key, dry_run),
            BeginMatchResponse,
            options,
        )

    def append_units(
        self,
        match_id: str,
        request: AppendUnitsRequest | Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
        dry_run: bool = False,
        options: RequestOptions | None = None,
    ) -> AppendUnitsResponse:
        """Add rounds (or a whole game, for a gamemode without rounds) to an open match. The request is accepted or
        refused whole.
        """
        return self._client._send(
            self._write(_match_path(match_id, "/units"), _as(AppendUnitsRequest, request), idempotency_key, dry_run),
            AppendUnitsResponse,
            options,
        )

    def heartbeat(
        self, match_id: str, *, idempotency_key: str | None = None, options: RequestOptions | None = None
    ) -> HeartbeatMatchResponse:
        """Say the match is still being played when no unit is ready; a match silent for 30 minutes is closed and held
        for review.
        """
        return self._client._send(
            self._write(_match_path(match_id, "/heartbeat"), None, idempotency_key, False),
            HeartbeatMatchResponse,
            options,
        )

    def finalize(
        self, match_id: str, *, idempotency_key: str | None = None, options: RequestOptions | None = None
    ) -> FinalizeMatchResponse:
        """Close the match and free its live session. A game without its result, or a missing round, holds it for an
        Organizer's review.
        """
        return self._client._send(
            self._write(_match_path(match_id, "/finalize"), None, idempotency_key, False),
            FinalizeMatchResponse,
            options,
        )

    def upload(
        self,
        request: UploadMatchRequest | Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
        dry_run: bool = False,
        options: RequestOptions | None = None,
    ) -> UploadMatchResponse:
        """A complete tracked match in one request.

        It never holds a live session; the same upload again changes nothing.
        """
        return self._client._send(
            self._write(_BASE + "/uploads", _as(UploadMatchRequest, request), idempotency_key, dry_run),
            UploadMatchResponse,
            options,
        )


class AsyncStats(_StatsCalls):
    """Stat submission from an ``AsyncHeir``. See ``Stats`` for what each call does."""

    def __init__(self, client: AsyncHeir) -> None:
        self._client = client

    async def gamemodes(self, *, options: RequestOptions | None = None) -> GamemodeCatalog:
        return await self._client._send(self._read("/gamemodes"), GamemodeCatalog, options)

    async def schemas(self, *, options: RequestOptions | None = None) -> StatSchemaCatalog:
        return await self._client._send(self._read("/schemas"), StatSchemaCatalog, options)

    async def submit_match(
        self, file: HeirMatchFile | Mapping[str, Any], *, options: RequestOptions | None = None
    ) -> MatchEntryReceipt:
        return await self._client._send(self._submit(_as(HeirMatchFile, file)), MatchEntryReceipt, options)

    async def begin_match(
        self,
        request: BeginMatchRequest | Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
        dry_run: bool = False,
        options: RequestOptions | None = None,
    ) -> BeginMatchResponse:
        return await self._client._send(
            self._write(_BASE + "/matches", _as(BeginMatchRequest, request), idempotency_key, dry_run),
            BeginMatchResponse,
            options,
        )

    async def append_units(
        self,
        match_id: str,
        request: AppendUnitsRequest | Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
        dry_run: bool = False,
        options: RequestOptions | None = None,
    ) -> AppendUnitsResponse:
        return await self._client._send(
            self._write(_match_path(match_id, "/units"), _as(AppendUnitsRequest, request), idempotency_key, dry_run),
            AppendUnitsResponse,
            options,
        )

    async def heartbeat(
        self, match_id: str, *, idempotency_key: str | None = None, options: RequestOptions | None = None
    ) -> HeartbeatMatchResponse:
        return await self._client._send(
            self._write(_match_path(match_id, "/heartbeat"), None, idempotency_key, False),
            HeartbeatMatchResponse,
            options,
        )

    async def finalize(
        self, match_id: str, *, idempotency_key: str | None = None, options: RequestOptions | None = None
    ) -> FinalizeMatchResponse:
        return await self._client._send(
            self._write(_match_path(match_id, "/finalize"), None, idempotency_key, False),
            FinalizeMatchResponse,
            options,
        )

    async def upload(
        self,
        request: UploadMatchRequest | Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
        dry_run: bool = False,
        options: RequestOptions | None = None,
    ) -> UploadMatchResponse:
        return await self._client._send(
            self._write(_BASE + "/uploads", _as(UploadMatchRequest, request), idempotency_key, dry_run),
            UploadMatchResponse,
            options,
        )
