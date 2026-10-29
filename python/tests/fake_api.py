"""A fake API behind httpx.MockTransport: each request is answered by the next step, and every request is kept."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

Step = Callable[[httpx.Request], httpx.Response]


class FakeAPI:
    def __init__(self, *steps: Step) -> None:
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.steps:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        return self.steps.pop(0)(request)

    @property
    def calls(self) -> int:
        return len(self.requests)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def body(self, index: int) -> Any:
        return json.loads(self.requests[index].content) if self.requests[index].content else None


def respond(status: int, body: Any, headers: dict[str, str] | None = None) -> Step:
    def step(request: httpx.Request) -> httpx.Response:
        content = body if isinstance(body, (str, bytes)) else json.dumps(body)
        return httpx.Response(
            status, content=content, headers={"content-type": "application/json", **(headers or {})}, request=request
        )

    return step


def api_error(status: int, code: str, message: str = "No.", headers: dict[str, str] | None = None) -> Step:
    return respond(status, {"error": code, "message": message}, headers)


def broken(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection reset", request=request)


def slow(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("no answer", request=request)


PLAYER = {
    "player": {
        "identifier": "A1B2C3D4E5F67890",
        "displayName": "Ada",
        "profileUrl": None,
        "mmr": None,
        "rank": None,
        "heirRating": None,
        "roster": None,
    }
}


def roster(name: str) -> dict[str, Any]:
    return {
        "id": name,
        "name": name,
        "tag": None,
        "logoUrl": None,
        "teamMmr": 1500,
        "provisional": False,
        "category": "competitive",
        "captain": None,
    }
