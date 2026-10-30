"""The official Python SDK for the Heir public API."""

from . import models
from ._client import AsyncHeir, Heir
from ._errors import (
    APIIssue,
    HeirAPIError,
    HeirConnectionError,
    HeirError,
    HeirInputError,
    HeirProtocolError,
    HeirTimeoutError,
)
from ._league import AsyncLeague, League
from ._pagination import AsyncPage, Page
from ._stats import AsyncStats, Stats, new_idempotency_key
from ._transport import DEFAULT_BASE_URL, RequestOptions
from ._types import Category, FixtureStatus, Metric
from ._version import __version__
from .models import *  # noqa: F403

__all__ = [
    "DEFAULT_BASE_URL",
    "APIIssue",
    "AsyncHeir",
    "AsyncLeague",
    "AsyncPage",
    "AsyncStats",
    "Category",
    "FixtureStatus",
    "Heir",
    "HeirAPIError",
    "HeirConnectionError",
    "HeirError",
    "HeirInputError",
    "HeirProtocolError",
    "HeirTimeoutError",
    "League",
    "Metric",
    "Page",
    "RequestOptions",
    "Stats",
    "__version__",
    "models",
    "new_idempotency_key",
    *models.__all__,
]
