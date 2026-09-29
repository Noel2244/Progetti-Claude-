"""Data contracts: schema, type, range, nullability, duplicate and timestamp checks.

A provider failing its contract must never silently corrupt the database:
records with ERROR issues are rejected (and reported); WARN records are kept
but flagged.
"""

from __future__ import annotations

from datetime import date, timedelta

from sports_engine.core.enums import MatchStatus
from sports_engine.normalization.records import (
    ParsedDataset,
    SourceMatchRecord,
    SourceOddsRecord,
    ValidationIssue,
)

MIN_DATE = date(1860, 1, 1)
MAX_GOALS = 40
MIN_ODDS = 1.0001
MAX_ODDS = 1001.0


def validate_match(rec: SourceMatchRecord, today: date | None = None) -> list[ValidationIssue]:
    today = today or date.today()
    issues: list[ValidationIssue] = []

    def err(code: str, msg: str) -> None:
        issues.append(ValidationIssue("ERROR", code, msg, rec.source, rec.source_match_key))

    def warn(code: str, msg: str) -> None:
        issues.append(ValidationIssue("WARN", code, msg, rec.source, rec.source_match_key))

    if not rec.home_team_raw or not rec.away_team_raw:
        err("MISSING_TEAM", "home or away team missing")
    elif rec.home_team_raw.strip().lower() == rec.away_team_raw.strip().lower():
        err("SAME_TEAM", f"home == away ({rec.home_team_raw})")
    if not isinstance(rec.match_date, date):
        err("BAD_DATE", f"match_date not a date: {rec.match_date!r}")
    elif not (MIN_DATE <= rec.match_date <= today + timedelta(days=730)):
        err("DATE_RANGE", f"implausible date {rec.match_date}")
    for name in ("home_goals", "away_goals", "ht_home_goals", "ht_away_goals"):
        v = getattr(rec, name)
        if v is not None and (not isinstance(v, int) or v < 0 or v > MAX_GOALS):
            err("GOALS_RANGE", f"{name}={v!r}")
    if (rec.home_goals is None) != (rec.away_goals is None):
        err("PARTIAL_SCORE", "only one side of the score present")
    if rec.status == MatchStatus.FINISHED and rec.home_goals is None:
        err("FINISHED_NO_SCORE", "finished match without score")
    if rec.home_goals is not None and rec.ht_home_goals is not None and rec.ht_away_goals is not None:
        if rec.ht_home_goals > rec.home_goals or rec.ht_away_goals > rec.away_goals:
            err("HT_GT_FT", "half-time goals exceed full-time goals")
    if rec.home_goals is not None and isinstance(rec.match_date, date) and rec.match_date > today + timedelta(days=1):
        err("FUTURE_RESULT", "result present for a future-dated match")
    if rec.status == MatchStatus.SCHEDULED and isinstance(rec.match_date, date) and rec.match_date < today - timedelta(days=3):
        warn("STALE_FIXTURE", "past match still without a result")
    return issues


def validate_odds(rec: SourceOddsRecord) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(rec.odds, float) or not (MIN_ODDS <= rec.odds <= MAX_ODDS):
        issues.append(ValidationIssue("ERROR", "ODDS_RANGE", f"odds={rec.odds!r}", rec.source, rec.source_match_key))
    if not rec.bookmaker or not rec.market or not rec.selection:
        issues.append(ValidationIssue("ERROR", "ODDS_KEYS", "missing bookmaker/market/selection", rec.source, rec.source_match_key))
    if rec.available_at is None:
        issues.append(ValidationIssue("WARN", "ODDS_NO_TIMESTAMP", "odds without availability time", rec.source, rec.source_match_key))
    return issues


def enforce_contract(ds: ParsedDataset, today: date | None = None) -> ParsedDataset:
    """Return a copy of ``ds`` containing only contract-compliant records, with issues appended."""
    good_matches: list[SourceMatchRecord] = []
    issues = list(ds.issues)
    seen: dict[str, SourceMatchRecord] = {}
    for rec in ds.matches:
        rec_issues = validate_match(rec, today)
        if rec.source_match_key in seen:
            rec_issues.append(
                ValidationIssue("ERROR", "DUPLICATE_KEY", "duplicate source key within dataset", rec.source, rec.source_match_key)
            )
        issues.extend(rec_issues)
        if not any(i.severity == "ERROR" for i in rec_issues):
            good_matches.append(rec)
            seen[rec.source_match_key] = rec
    valid_keys = {m.source_match_key for m in good_matches}
    good_odds = []
    for o in ds.odds:
        o_issues = validate_odds(o)
        if o.source_match_key not in valid_keys:
            o_issues.append(ValidationIssue("ERROR", "ORPHAN_ODDS", "odds for a rejected/unknown match", o.source, o.source_match_key))
        issues.extend(o_issues)
        if not any(i.severity == "ERROR" for i in o_issues):
            good_odds.append(o)
    return ParsedDataset(
        provider=ds.provider,
        dataset_key=ds.dataset_key,
        raw_sha256=ds.raw_sha256,
        matches=good_matches,
        odds=good_odds,
        issues=issues,
        parser_version=ds.parser_version,
    )
