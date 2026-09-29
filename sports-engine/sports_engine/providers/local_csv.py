"""Manual import of local files in a documented standard format.

Place files in ``data/inbox/``:

* ``matches_*.csv`` columns:
  ``competition_id,season,date,time,home,away,home_goals,away_goals,status``
  (``time`` optional local HH:MM; goals empty for fixtures)
* ``odds_*.csv`` columns:
  ``competition_id,date,home,away,bookmaker,market,selection,line,odds,snapshot_type,captured_at``
  ``captured_at`` is REQUIRED (ISO-8601 with timezone): odds without a capture
  time cannot be used point-in-time and are rejected.
* ``football_data/*.csv``: files downloaded manually from football-data.co.uk
  (parsed with the football-data parser; acquisition = manual_import).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Iterable

from sports_engine.core.enums import DataClass, MatchStatus, SnapshotType, SourceTier, TimestampQuality
from sports_engine.core.timeutils import local_to_utc, parse_iso
from sports_engine.entity.competitions import get_competition, season_label
from sports_engine.normalization.records import (
    ParsedDataset,
    SourceMatchRecord,
    SourceOddsRecord,
    ValidationIssue,
)
from sports_engine.providers.base import DataProvider, DatasetDescriptor, ProviderInfo

PARSER_VERSION = "1"
MATCH_COLUMNS = ["competition_id", "season", "date", "time", "home", "away", "home_goals", "away_goals", "status"]
ODDS_COLUMNS = ["competition_id", "date", "home", "away", "bookmaker", "market", "selection", "line", "odds",
                "snapshot_type", "captured_at"]
VALID_SELECTIONS = {"1X2": {"H", "D", "A"}, "OU": {"OVER", "UNDER"}, "AH": {"AH_HOME", "AH_AWAY"}, "BTTS": {"YES", "NO"}}


def match_key(competition_id: str, d: date, home: str, away: str) -> str:
    return f"{competition_id}:{d.isoformat()}:{home.strip()}:{away.strip()}"


class LocalCSVProvider(DataProvider):
    info = ProviderInfo(
        name="local_csv",
        display_name="Local manual import",
        homepage="file://data/inbox",
        license_id="user-provided",
        license_url=None,
        terms_url=None,
        attribution=None,
        source_tier=SourceTier.UNVERIFIED,
        data_classes=(DataClass.LIVE_OUT_OF_SAMPLE,),
        capabilities=("results", "fixtures", "odds"),
        allowed_hosts=(),
        notes="User-entered data. Reliability depends on the user; odds require capture timestamps.",
    )

    def discover(self, competition_ids: Iterable[str], seasons: Iterable[int] | None = None) -> list[DatasetDescriptor]:
        return []  # files are discovered by the ingestion pipeline from the inbox

    def parse(self, descriptor: DatasetDescriptor, content: bytes, raw_sha256: str,
              acquired_at: datetime | None = None) -> ParsedDataset:
        ds = ParsedDataset(self.name, descriptor.dataset_key, raw_sha256, parser_version=PARSER_VERSION)
        text = content.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        if descriptor.kind == "odds":
            self._parse_odds(ds, rows, raw_sha256)
        else:
            self._parse_matches(ds, rows, raw_sha256)
        return ds

    def _parse_matches(self, ds: ParsedDataset, rows: list[dict], sha: str) -> None:
        for i, r in enumerate(rows):
            try:
                comp = get_competition(r["competition_id"].strip())
                d = date.fromisoformat(r["date"].strip())
                hhmm = (r.get("time") or "").strip() or None
                hg = r.get("home_goals", "").strip()
                ag = r.get("away_goals", "").strip()
                start_year = int((r.get("season") or "").strip()[:4] or (d.year if d.month >= 7 else d.year - 1))
            except (KeyError, ValueError) as exc:
                ds.issues.append(ValidationIssue("ERROR", "PARSE", f"row {i}: {exc}", self.name, ds.dataset_key))
                continue
            finished = hg != "" and ag != ""
            status = MatchStatus(r.get("status").strip().upper()) if r.get("status") else (
                MatchStatus.FINISHED if finished else MatchStatus.SCHEDULED)
            ds.matches.append(SourceMatchRecord(
                source=self.name,
                source_match_key=match_key(comp.competition_id, d, r["home"], r["away"]),
                competition_id=comp.competition_id,
                season=season_label(start_year, comp.season_style),
                season_start_year=start_year,
                match_date=d,
                home_team_raw=r["home"].strip(),
                away_team_raw=r["away"].strip(),
                timezone=comp.timezone,
                kickoff_local_time=hhmm,
                kickoff_utc=local_to_utc(d, hhmm, comp.timezone) if hhmm else None,
                timestamp_quality=TimestampQuality.EXACT if hhmm else TimestampQuality.DATE_ONLY,
                home_goals=int(hg) if finished else None,
                away_goals=int(ag) if finished else None,
                status=status,
                raw_sha256=sha,
                raw_row=i,
            ))

    def _parse_odds(self, ds: ParsedDataset, rows: list[dict], sha: str) -> None:
        for i, r in enumerate(rows):
            try:
                comp = get_competition(r["competition_id"].strip())
                d = date.fromisoformat(r["date"].strip())
                market = r["market"].strip().upper()
                sel = r["selection"].strip().upper()
                if sel not in VALID_SELECTIONS.get(market, set()):
                    raise ValueError(f"invalid selection {sel!r} for market {market!r}")
                captured = parse_iso(r["captured_at"])
                if captured is None:
                    raise ValueError("captured_at is required")
                odds = float(r["odds"])
                line = float(r["line"]) if (r.get("line") or "").strip() else None
                st = SnapshotType((r.get("snapshot_type") or "PRE_MATCH").strip().upper())
            except (KeyError, ValueError) as exc:
                ds.issues.append(ValidationIssue("ERROR", "PARSE", f"odds row {i}: {exc}", self.name, ds.dataset_key))
                continue
            key = match_key(comp.competition_id, d, r["home"], r["away"])
            ds.odds.append(SourceOddsRecord(self.name, key, r["bookmaker"].strip().lower(), market, sel, odds, st,
                                            captured, TimestampQuality.EXACT, line, sha))
            # an odds file may reference a fixture that is not in any matches file
            if not any(m.source_match_key == key for m in ds.matches):
                start_year = d.year if d.month >= 7 else d.year - 1
                ds.matches.append(SourceMatchRecord(
                    source=self.name, source_match_key=key, competition_id=comp.competition_id,
                    season=season_label(start_year, comp.season_style), season_start_year=start_year,
                    match_date=d, home_team_raw=r["home"].strip(), away_team_raw=r["away"].strip(),
                    timezone=comp.timezone, status=MatchStatus.SCHEDULED, raw_sha256=sha, raw_row=i,
                ))
