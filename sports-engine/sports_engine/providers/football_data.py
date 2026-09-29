"""football-data.co.uk - results, match statistics and bookmaker odds (1X2, O/U 2.5, AH).

Terms (read them yourself: https://www.football-data.co.uk/data.php):
    "it's all FREE, however its use is intended for private individuals only,
     NOT commercial or data training products using automated bots/scrapers/AI."
    "All data provided by Football-Data are made available for the purposes of
     league match prediction only."
Its robots.txt blocks AI crawlers. Consequences for this engine:

* the provider is **opt-in** (``enabled`` AND ``terms_acknowledged``);
* it is meant to be run by the private individual who owns this installation,
  with an honest user agent, robots.txt honoured and a slow request rate;
* raw files are never committed or redistributed (data/ is git-ignored);
* manual import (``data/inbox/football_data/*.csv``) is always available.

Odds timing (from notes.txt): "Betting odds for weekend games are collected
Friday afternoons, and on Tuesday afternoons for midweek games." Closing odds
(columns with ``C``) are the last prices before kickoff and exist from 2019/20.
We therefore stamp:

* pre-closing odds: ``available_at`` = conservative collection estimate
  (Friday / Tuesday 18:00 UK), capped at kickoff-30min -> ``APPROXIMATE``;
* closing odds: ``available_at`` = kickoff -> only visible to ``as_of >= kickoff``;
* ``fixtures.csv`` odds: ``available_at`` = our own download time -> ``EXACT``.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from typing import Iterable

from sports_engine.core.enums import DataClass, MatchStatus, SnapshotType, SourceTier, TimestampQuality
from sports_engine.core.timeutils import local_to_utc, next_local_midnight_utc
from sports_engine.entity.competitions import get_competition, load_competitions, season_label
from sports_engine.normalization.records import (
    ParsedDataset,
    SourceMatchRecord,
    SourceOddsRecord,
    ValidationIssue,
)
from sports_engine.providers.base import DataProvider, DatasetDescriptor, ProviderInfo

BASE = "https://www.football-data.co.uk"
UK_TZ = "Europe/London"
PARSER_VERSION = "1"

BOOKMAKERS = {
    "B365": "bet365", "BW": "bwin", "IW": "interwetten", "LB": "ladbrokes", "PS": "pinnacle", "P": "pinnacle",
    "WH": "williamhill", "SJ": "stanjames", "VC": "vcbet", "GB": "gamebookers", "BS": "bluesquare",
    "SB": "sportingbet", "SO": "sportingodds", "SY": "stanleybet", "1XB": "1xbet", "BF": "betfair_sportsbook",
    "BFE": "betfair_exchange", "CL": "coral",
    "Max": "agg_max", "Avg": "agg_avg", "BbMx": "agg_betbrain_max", "BbAv": "agg_betbrain_avg",
}
AGGREGATE_BOOKMAKERS = {"agg_max", "agg_avg", "agg_betbrain_max", "agg_betbrain_avg"}

_1X2_PREFIXES = ["BbMx", "BbAv", "B365", "1XB", "BFE", "Max", "Avg", "BW", "IW", "LB", "PS", "WH", "SJ", "VC",
                 "GB", "BS", "SB", "SO", "SY", "BF", "CL"]
_OU_PREFIXES = ["BbMx", "BbAv", "B365", "BFE", "Max", "Avg", "GB", "BF", "P"]
_AH_PREFIXES = ["BbMx", "BbAv", "B365", "BFE", "Max", "Avg", "LB", "GB", "BW", "P"]


def _alt(prefixes: list[str]) -> str:
    return "|".join(re.escape(p) for p in sorted(prefixes, key=len, reverse=True))


RE_1X2 = re.compile(rf"^({_alt(_1X2_PREFIXES)})(C?)([HDA])$")
RE_OU = re.compile(rf"^({_alt(_OU_PREFIXES)})(C?)([<>])2\.5$")
RE_AH = re.compile(rf"^({_alt(_AH_PREFIXES)})(C?)AH([HA])$")

STAT_COLUMNS = {
    "HS": "home_shots", "AS": "away_shots", "HST": "home_shots_on_target", "AST": "away_shots_on_target",
    "HHW": "home_woodwork", "AHW": "away_woodwork", "HC": "home_corners", "AC": "away_corners",
    "HF": "home_fouls", "AF": "away_fouls", "HFKC": "home_free_kicks_conceded", "AFKC": "away_free_kicks_conceded",
    "HO": "home_offsides", "AO": "away_offsides", "HY": "home_yellow", "AY": "away_yellow",
    "HR": "home_red", "AR": "away_red", "HBP": "home_booking_points", "ABP": "away_booking_points",
    "Attendance": "attendance",
}


def fd_season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def parse_fd_date(s: str) -> date:
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"bad date {s!r}")


def prematch_collection_estimate(d: date, kickoff_utc: datetime | None) -> datetime:
    """Conservative upper bound of when football-data collected pre-closing odds."""
    wd = d.weekday()  # Mon=0
    if wd in (1, 2, 3):          # Tue/Wed/Thu -> Tuesday of the same week
        coll_day = d - timedelta(days=wd - 1)
    else:                        # Fri/Sat/Sun/Mon -> the Friday on/before the match
        coll_day = d - timedelta(days=(wd - 4) % 7)
    est = local_to_utc(coll_day, "18:00", UK_TZ)
    if kickoff_utc is not None:
        est = min(est, kickoff_utc - timedelta(minutes=30))
    return est


def _float(v: str | None) -> float | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return f


def _int(v: str | None) -> int | None:
    f = _float(v)
    return None if f is None else int(round(f))


class FootballDataProvider(DataProvider):
    info = ProviderInfo(
        name="football_data",
        display_name="Football-Data.co.uk",
        homepage=BASE,
        license_id="Football-Data-Private-Use",
        license_url=f"{BASE}/data.php",
        terms_url=f"{BASE}/disclaimer.php",
        attribution="Data: Football-Data.co.uk",
        source_tier=SourceTier.REPUTABLE_STRUCTURED,
        data_classes=(DataClass.LONG_TERM, DataClass.POINT_IN_TIME_READY, DataClass.LIVE_OUT_OF_SAMPLE),
        capabilities=("results", "half_time", "stats", "odds", "closing_odds", "fixtures", "kickoff_times"),
        allowed_hosts=("www.football-data.co.uk", "football-data.co.uk"),
        requires_opt_in=True,
        notes="Results from 1993/94, odds from 2000/01, closing odds from 2019/20, kickoff times from 2019/20.",
        restrictions=(
            "private individuals only",
            "league match prediction only",
            "not for commercial or data-training products",
            "robots.txt blocks AI crawlers",
            "do not redistribute raw files",
        ),
    )

    def enabled_reason(self) -> str | None:
        if self.settings is None:
            return "no settings"
        if not self.settings.get("providers.football_data.enabled", False):
            return "football_data is opt-in: set providers.football_data.enabled: true"
        if not self.settings.get("providers.football_data.terms_acknowledged", False):
            return "read football-data.co.uk terms, then set providers.football_data.terms_acknowledged: true"
        return None

    def is_enabled(self) -> bool:
        return self.enabled_reason() is None

    def discover(self, competition_ids: Iterable[str], seasons: Iterable[int] | None = None) -> list[DatasetDescriptor]:
        today = date.today()
        cur = today.year if today.month >= 7 else today.year - 1
        first = int(self.settings.get("providers.football_data.first_season", 1993)) if self.settings else 1993
        years = sorted(set(seasons)) if seasons else list(range(first, cur + 1))
        out = []
        for cid in competition_ids:
            code = get_competition(cid).source_code(self.name)
            if not code:
                continue
            for y in years:
                if y > cur:
                    continue
                closed = date(y + 1, 7, 31) < today - timedelta(days=30)
                sc = fd_season_code(y)
                out.append(DatasetDescriptor(self.name, f"mmz4281/{sc}/{code}", f"{BASE}/mmz4281/{sc}/{code}.csv",
                                             "results_odds", competition_id=cid, season=season_label(y),
                                             immutable=closed, file_ext="csv"))
        out.append(DatasetDescriptor(self.name, "fixtures", f"{BASE}/fixtures.csv", "fixtures",
                                     competition_id=",".join(sorted(competition_ids)), immutable=False, file_ext="csv"))
        return out

    # ------------------------------------------------------------------ parsing
    def parse(self, descriptor: DatasetDescriptor, content: bytes, raw_sha256: str,
              acquired_at: datetime | None = None) -> ParsedDataset:
        ds = ParsedDataset(self.name, descriptor.dataset_key, raw_sha256, parser_version=PARSER_VERSION)
        text = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        reader = csv.reader(io.StringIO(text or ""))
        try:
            header = [h.strip().lstrip("﻿") for h in next(reader)]
        except StopIteration:
            ds.issues.append(ValidationIssue("ERROR", "EMPTY", "empty file", self.name, descriptor.dataset_key))
            return ds
        while header and header[-1] == "":
            header.pop()
        is_fixtures = descriptor.kind == "fixtures"
        div_to_cid = {c.source_code(self.name): cid for cid, c in load_competitions().items() if c.source_code(self.name)}
        wanted = set((descriptor.competition_id or "").split(","))
        col_1x2 = [(c, RE_1X2.match(c)) for c in header]
        col_ou = [(c, RE_OU.match(c)) for c in header]
        col_ah = [(c, RE_AH.match(c)) for c in header]
        seen: dict[str, int] = {}
        for i, cells in enumerate(reader):
            if not any(x.strip() for x in cells):
                continue
            row = {h: (cells[j].strip() if j < len(cells) else "") for j, h in enumerate(header)}
            div = row.get("Div", "")
            cid = div_to_cid.get(div)
            if cid is None or (wanted - {""} and cid not in wanted):
                continue
            comp = get_competition(cid)
            try:
                d = parse_fd_date(row.get("Date", ""))
            except ValueError as exc:
                ds.issues.append(ValidationIssue("ERROR", "PARSE", f"row {i}: {exc}", self.name, descriptor.dataset_key))
                continue
            home = row.get("HomeTeam") or row.get("Home") or ""
            away = row.get("AwayTeam") or row.get("Away") or ""
            hhmm = (row.get("Time") or "").strip()[:5] or None
            kickoff = local_to_utc(d, hhmm, UK_TZ) if hhmm else None
            start_year = d.year if d.month >= 7 else d.year - 1
            if descriptor.season:
                start_year = int(descriptor.season[:4])
            hg = _int(row.get("FTHG", row.get("HG")))
            ag = _int(row.get("FTAG", row.get("AG")))
            status = MatchStatus.FINISHED if (hg is not None and ag is not None) else MatchStatus.SCHEDULED
            base_key = f"{div}:{start_year}:{d.isoformat()}:{home}:{away}"
            n = seen.get(base_key, 0)
            seen[base_key] = n + 1
            key = base_key if n == 0 else f"{base_key}#{n}"
            stats = {name: _int(row.get(col)) for col, name in STAT_COLUMNS.items() if row.get(col, "") != ""}
            ds.matches.append(
                SourceMatchRecord(
                    source=self.name,
                    source_match_key=key,
                    competition_id=cid,
                    season=season_label(start_year, comp.season_style),
                    season_start_year=start_year,
                    match_date=d,
                    home_team_raw=home,
                    away_team_raw=away,
                    timezone=UK_TZ,  # football-data dates/times are UK local
                    kickoff_local_time=hhmm,
                    kickoff_utc=kickoff,
                    timestamp_quality=TimestampQuality.EXACT if hhmm else TimestampQuality.DATE_ONLY,
                    home_goals=hg if status == MatchStatus.FINISHED else None,
                    away_goals=ag if status == MatchStatus.FINISHED else None,
                    ht_home_goals=_int(row.get("HTHG")),
                    ht_away_goals=_int(row.get("HTAG")),
                    status=status,
                    referee=row.get("Referee") or None,
                    stats=stats,
                    raw_sha256=raw_sha256,
                    raw_row=i,
                )
            )
            ds.odds.extend(self._odds(row, key, d, kickoff, raw_sha256, col_1x2, col_ou, col_ah, is_fixtures, acquired_at))
        return ds

    def _odds(self, row, key, d, kickoff, sha, col_1x2, col_ou, col_ah, is_fixtures, acquired_at) -> list[SourceOddsRecord]:
        out: list[SourceOddsRecord] = []

        def stamp(closing: bool) -> tuple[SnapshotType, datetime | None, TimestampQuality]:
            if closing:
                if kickoff is not None:
                    return SnapshotType.CLOSING, kickoff, TimestampQuality.EXACT
                return SnapshotType.CLOSING, next_local_midnight_utc(d, UK_TZ), TimestampQuality.DATE_ONLY
            if is_fixtures and acquired_at is not None:
                return SnapshotType.PRE_MATCH, acquired_at, TimestampQuality.EXACT
            return SnapshotType.PRE_MATCH, prematch_collection_estimate(d, kickoff), TimestampQuality.APPROXIMATE

        for col, m in col_1x2:
            if not m:
                continue
            o = _float(row.get(col))
            if o is None or o <= 1.0:
                continue
            st, at, tq = stamp(m.group(2) == "C")
            out.append(SourceOddsRecord(self.name, key, BOOKMAKERS[m.group(1)], "1X2", m.group(3), o, st, at, tq, None, sha))
        for col, m in col_ou:
            if not m:
                continue
            o = _float(row.get(col))
            if o is None or o <= 1.0:
                continue
            st, at, tq = stamp(m.group(2) == "C")
            sel = "OVER" if m.group(3) == ">" else "UNDER"
            out.append(SourceOddsRecord(self.name, key, BOOKMAKERS[m.group(1)], "OU", sel, o, st, at, tq, 2.5, sha))
        line_pre = _float(row.get("AHh")) if row.get("AHh") else _float(row.get("BbAHh"))
        line_close = _float(row.get("AHCh"))
        for col, m in col_ah:
            if not m:
                continue
            o = _float(row.get(col))
            closing = m.group(2) == "C"
            line = line_close if closing else line_pre
            if o is None or o <= 1.0 or line is None:
                continue
            st, at, tq = stamp(closing)
            sel = "AH_HOME" if m.group(3) == "H" else "AH_AWAY"
            out.append(SourceOddsRecord(self.name, key, BOOKMAKERS[m.group(1)], "AH", sel, o, st, at, tq, line, sha))
        return out
