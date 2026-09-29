"""Provider-agnostic normalized records.

Providers translate their native formats into these records; nothing
provider-specific crosses this boundary into the core domain.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from sports_engine.core.enums import MatchStatus, SnapshotType, TimestampQuality


@dataclass
class SourceMatchRecord:
    source: str
    source_match_key: str
    competition_id: str
    season: str                     # e.g. "2024-2025" (or "2024" for calendar-year leagues)
    season_start_year: int
    match_date: date                # local calendar date
    home_team_raw: str
    away_team_raw: str
    timezone: str
    kickoff_local_time: str | None = None   # "HH:MM" local, when known
    kickoff_utc: datetime | None = None
    timestamp_quality: TimestampQuality = TimestampQuality.DATE_ONLY
    home_goals: int | None = None
    away_goals: int | None = None
    ht_home_goals: int | None = None
    ht_away_goals: int | None = None
    status: MatchStatus = MatchStatus.UNKNOWN
    round: str | None = None
    venue: str | None = None
    referee: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)   # shots, corners, cards, xg ...
    extra: dict[str, Any] = field(default_factory=dict)   # managers etc.
    raw_sha256: str | None = None
    raw_row: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceOddsRecord:
    source: str
    source_match_key: str
    bookmaker: str
    market: str            # "1X2", "OU", "AH", "BTTS"
    selection: str         # "H","D","A","OVER","UNDER","AH_HOME","AH_AWAY","YES","NO"
    odds: float
    snapshot_type: SnapshotType
    available_at: datetime | None
    timestamp_quality: TimestampQuality
    line: float | None = None
    raw_sha256: str | None = None


@dataclass
class ValidationIssue:
    severity: str          # ERROR (record rejected) | WARN (kept, flagged)
    code: str
    message: str
    source: str | None = None
    key: str | None = None


@dataclass
class ParsedDataset:
    provider: str
    dataset_key: str
    raw_sha256: str
    matches: list[SourceMatchRecord] = field(default_factory=list)
    odds: list[SourceOddsRecord] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    # post-match statistics keyed by source_match_key (e.g. xG aggregated from events)
    stat_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    parser_version: str = "1"
