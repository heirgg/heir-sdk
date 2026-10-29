"""Everything the SDK raises extends HeirError, so one `except` catches it all."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


class HeirError(Exception):
    """The base of every error this SDK raises."""


@dataclass(frozen=True)
class APIIssue:
    """One field the API could not accept, named when it can be."""

    path: str
    message: str


class HeirAPIError(HeirError):
    """The API answered with an error.

    `code` is the stable code to branch on (`rate-limited`, `league-not-found`, `rejected`, ...), `message` a sentence
    for a person whose wording can change. `status_code` is the HTTP status and `retry_after`, on a 429, how many
    seconds the API asked you to wait.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        issues: list[APIIssue] | None = None,
        retry_after: float | None = None,
        headers: httpx.Headers | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.issues = issues or []
        self.retry_after = retry_after
        self.headers = headers if headers is not None else httpx.Headers()
        self.body = body

    @property
    def is_rate_limited(self) -> bool:
        """Too many requests this minute, or as many live sessions open as the League's plan allows."""
        return self.status_code == 429

    def __str__(self) -> str:
        return f"{self.code} ({self.status_code}): {self.message}"

    @classmethod
    def from_response(cls, response: httpx.Response) -> HeirAPIError:
        """Read the API's `{error, message, issues?}` envelope; an answer that is not one still becomes an error you can
        inspect.
        """
        text = response.text
        body: Any = text
        with contextlib.suppress(ValueError):
            body = json.loads(text) if text else None
        envelope = (
            body
            if isinstance(body, dict) and isinstance(body.get("error"), str) and isinstance(body.get("message"), str)
            else None
        )
        issues = (
            [
                APIIssue(path=str(i.get("path", "")), message=str(i.get("message", "")))
                for i in envelope.get("issues") or []
            ]
            if envelope
            else []
        )
        fallback = f"The API answered {response.status_code} {response.reason_phrase}".rstrip() + "."
        return cls(
            status_code=response.status_code,
            code=envelope["error"] if envelope else "unknown",
            message=envelope["message"] if envelope else fallback,
            issues=issues,
            retry_after=parse_retry_after(response.headers.get("retry-after")),
            headers=response.headers,
            body=body,
        )


class HeirConnectionError(HeirError):
    """The API could not be reached, or the connection failed before an answer arrived. `__cause__` is the underlying
    error.
    """


class HeirTimeoutError(HeirConnectionError):
    """No answer arrived within the request's timeout."""

    def __init__(self, url: str, timeout: float | None) -> None:
        super().__init__(f"No answer from {url} within {timeout} s." if timeout else f"No answer from {url} in time.")
        self.timeout = timeout


def parse_retry_after(header: str | None) -> float | None:
    """`Retry-After` as seconds, from either form the header takes: a count of seconds or an HTTP date."""
    if not header:
        return None
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    try:
        at = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return max(0.0, (at - datetime.now(timezone.utc)).total_seconds())
