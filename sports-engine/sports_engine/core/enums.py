"""Shared enumerations. Values are persisted, so never rename existing members."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class TimestampQuality(StrEnum):
    EXACT = "EXACT"              # recorded timestamp (e.g. official kickoff time)
    APPROXIMATE = "APPROXIMATE"  # inferred from a documented schedule / bounded estimate
    DATE_ONLY = "DATE_ONLY"      # only the calendar date is known
    UNKNOWN = "UNKNOWN"


TIMESTAMP_QUALITY_SCORE = {
    TimestampQuality.EXACT: 1.0,
    TimestampQuality.APPROXIMATE: 0.7,
    TimestampQuality.DATE_ONLY: 0.5,
    TimestampQuality.UNKNOWN: 0.0,
}


class DataClass(StrEnum):
    """Historical data classification (directive section 10)."""

    LONG_TERM = "LONG_TERM"
    MEDIUM_TERM = "MEDIUM_TERM"
    RECENT = "RECENT"
    POINT_IN_TIME_READY = "POINT_IN_TIME_READY"
    NON_POINT_IN_TIME = "NON_POINT_IN_TIME"
    POST_MATCH_ONLY = "POST_MATCH_ONLY"
    LIVE_OUT_OF_SAMPLE = "LIVE_OUT_OF_SAMPLE"


class MatchStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    FINISHED = "FINISHED"
    POSTPONED = "POSTPONED"
    AWARDED = "AWARDED"
    UNKNOWN = "UNKNOWN"


class SnapshotType(StrEnum):
    OPENING = "OPENING"
    PRE_MATCH = "PRE_MATCH"
    CLOSING = "CLOSING"


class Freshness(StrEnum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class DecisionStatus(StrEnum):
    STRONG_CANDIDATE = "STRONG_CANDIDATE"
    CANDIDATE = "CANDIDATE"
    WATCH = "WATCH"
    NO_BET = "NO_BET"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SourceTier(int, Enum):
    """Source reliability hierarchy (directive section 30); lower is more reliable."""

    OFFICIAL_COMPETITION = 1
    OFFICIAL_CLUB = 2
    OFFICIAL_TEAM = 3
    REPUTABLE_STRUCTURED = 4
    REPUTABLE_JOURNALISM = 5
    SECONDARY = 6
    SOCIAL_MEDIA = 7
    UNVERIFIED = 8


SOURCE_TIER_RELIABILITY = {
    SourceTier.OFFICIAL_COMPETITION: 1.0,
    SourceTier.OFFICIAL_CLUB: 0.95,
    SourceTier.OFFICIAL_TEAM: 0.95,
    SourceTier.REPUTABLE_STRUCTURED: 0.9,
    SourceTier.REPUTABLE_JOURNALISM: 0.75,
    SourceTier.SECONDARY: 0.7,
    SourceTier.SOCIAL_MEDIA: 0.3,
    SourceTier.UNVERIFIED: 0.1,
}


class Outcome1X2(StrEnum):
    HOME = "H"
    DRAW = "D"
    AWAY = "A"


OUTCOMES_1X2 = ("H", "D", "A")
