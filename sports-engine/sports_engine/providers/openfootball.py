"""openfootball / football.json - public-domain (CC0) results and fixtures.

* Repository: https://github.com/openfootball/football.json
* License: CC0-1.0 (public domain).
* Coverage: top European leagues from 2010-11 (Serie A from 2013-14) to the
  current season, including *future fixtures* (used by live paper mode).
* Kickoff times are local times of the competition.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Iterable

from sports_engine.core.enums import DataClass, MatchStatus, SourceTier, TimestampQuality
from sports_engine.core.timeutils import local_to_utc
from sports_engine.entity.competitions import get_competition, season_label
from sports_engine.normalization.records import ParsedDataset, SourceMatchRecord, ValidationIssue
from sports_engine.providers.base import DataProvider, DatasetDescriptor, ProviderInfo

BASE_URL = "https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{code}.json"
PARSER_VERSION = "1"
FIRST_SEASON = 2010


def of_season(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def current_season_start(today: date | None = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


class OpenFootballProvider(DataProvider):
    info = ProviderInfo(
        name="openfootball",
        display_name="openfootball football.json",
        homepage="https://github.com/openfootball/football.json",
        license_id="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        terms_url="https://github.com/openfootball/football.json",
        attribution=None,
        source_tier=SourceTier.SECONDARY,
        data_classes=(DataClass.MEDIUM_TERM, DataClass.RECENT, DataClass.POINT_IN_TIME_READY, DataClass.LIVE_OUT_OF_SAMPLE),
        capabilities=("results", "fixtures", "kickoff_times", "half_time"),
        allowed_hosts=("raw.githubusercontent.com",),
        notes="Community-maintained; current season auto-updated daily upstream but can lag. "
        "Some knockout/final scores missing.",
    )

    def discover(self, competition_ids: Iterable[str], seasons: Iterable[int] | None = None) -> list[DatasetDescriptor]:
        today = date.today()
        cur = current_season_start(today)
        years = sorted(set(seasons)) if seasons else list(range(FIRST_SEASON, cur + 1))
        out = []
        for cid in competition_ids:
            code = get_competition(cid).source_code(self.name)
            if not code:
                continue
            for y in years:
                if y > cur:
                    continue
                # a season is closed (immutable) once it ended comfortably in the past
                closed = date(y + 1, 7, 31) < today - timedelta(days=30)
                out.append(
                    DatasetDescriptor(
                        provider=self.name,
                        dataset_key=f"{of_season(y)}/{code}",
                        url=BASE_URL.format(season=of_season(y), code=code),
                        kind="results",
                        competition_id=cid,
                        season=season_label(y),
                        immutable=closed,
                        file_ext="json",
                    )
                )
        return out

    def parse(self, descriptor: DatasetDescriptor, content: bytes, raw_sha256: str,
              acquired_at=None) -> ParsedDataset:
        ds = ParsedDataset(self.name, descriptor.dataset_key, raw_sha256, parser_version=PARSER_VERSION)
        try:
            doc = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            ds.issues.append(ValidationIssue("ERROR", "PARSE", str(exc), self.name, descriptor.dataset_key))
            return ds
        matches = doc.get("matches")
        if matches is None:  # legacy layout: rounds -> matches
            matches = [m for r in doc.get("rounds", []) for m in r.get("matches", [])]
        cid = descriptor.competition_id
        comp = get_competition(cid)
        start_year = int(descriptor.dataset_key[:4])
        seen: dict[str, int] = {}
        today = date.today()
        for i, m in enumerate(matches):
            try:
                d = date.fromisoformat(m["date"])
                home = m["team1"]["name"] if isinstance(m["team1"], dict) else m["team1"]
                away = m["team2"]["name"] if isinstance(m["team2"], dict) else m["team2"]
            except (KeyError, ValueError, TypeError) as exc:
                ds.issues.append(ValidationIssue("ERROR", "PARSE", f"match {i}: {exc}", self.name, descriptor.dataset_key))
                continue
            hhmm = (m.get("time") or "").strip()[:5] or None
            if hhmm and (len(hhmm) != 5 or hhmm[2] != ":"):
                ds.issues.append(ValidationIssue("WARN", "BAD_TIME", f"unparseable time {m.get('time')!r}", self.name, descriptor.dataset_key))
                hhmm = None
            score = m.get("score") or {}
            if isinstance(score, list):  # format drift seen upstream (2025-26): bare [home, away] = full time
                score = {"ft": score} if len(score) == 2 else {}
                ds.issues.append(ValidationIssue("WARN", "FORMAT_DRIFT", f"match {i}: list-shaped score", self.name, descriptor.dataset_key))
            ft = score.get("ft") or ([m.get("score1"), m.get("score2")] if m.get("score1") is not None else None)
            ht = score.get("ht")
            hg = ag = hth = hta = None
            if ft and len(ft) == 2 and ft[0] is not None:
                hg, ag = int(ft[0]), int(ft[1])
            if ht and len(ht) == 2 and ht[0] is not None:
                hth, hta = int(ht[0]), int(ht[1])
            if hg is not None:
                status = MatchStatus.FINISHED
            elif d >= today:
                status = MatchStatus.SCHEDULED
            else:
                status = MatchStatus.UNKNOWN  # past fixture without score: data gap or postponement
            base_key = f"{descriptor.dataset_key}:{d.isoformat()}:{home}:{away}"
            n = seen.get(base_key, 0)
            seen[base_key] = n + 1
            extra = {k: score[k] for k in ("et", "p") if k in score}
            ds.matches.append(
                SourceMatchRecord(
                    source=self.name,
                    source_match_key=base_key if n == 0 else f"{base_key}#{n}",
                    competition_id=cid,
                    season=season_label(start_year, comp.season_style),
                    season_start_year=start_year,
                    match_date=d,
                    home_team_raw=home.strip(),
                    away_team_raw=away.strip(),
                    timezone=comp.timezone,
                    kickoff_local_time=hhmm,
                    kickoff_utc=local_to_utc(d, hhmm, comp.timezone) if hhmm else None,
                    timestamp_quality=TimestampQuality.EXACT if hhmm else TimestampQuality.DATE_ONLY,
                    home_goals=hg,
                    away_goals=ag,
                    ht_home_goals=hth,
                    ht_away_goals=hta,
                    status=status,
                    round=m.get("round"),
                    extra=extra,
                    raw_sha256=raw_sha256,
                    raw_row=i,
                )
            )
        return ds
