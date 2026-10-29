"""Query parameter values, as the API declares them."""

from __future__ import annotations

from typing import Literal

#: A rating scope.
Category = Literal["overall", "competitive", "casual"]
#: What a leaderboard is ordered by.
Metric = Literal["mmr", "heirRating", "wins", "losses"]
#: Which fixtures to list.
FixtureStatus = Literal["scheduled", "played", "cancelled"]
