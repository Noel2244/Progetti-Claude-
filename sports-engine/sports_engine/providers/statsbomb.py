"""StatsBomb Open Data - event data (incl. xG), lineups, match metadata.

* Repository: https://github.com/statsbomb/open-data
* Terms: StatsBomb public data user agreement - credit "StatsBomb" as the data
  source (and use their logo) when publishing analysis. See LICENSE.pdf upstream.
* Coverage: selected competitions/seasons only (e.g. Serie A 2015/16 complete).

Point-in-time note: open data was published years after the matches. xG *values*
are post-match facts, but this particular dataset did not exist at the time, so
backtests using it are NON_POINT_IN_TIME with respect to data availability.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Iterable

from sports_engine.core.enums import DataClass, MatchStatus, SourceTier, TimestampQuality
from sports_engine.core.timeutils import local_to_utc
from sports_engine.entity.competitions import get_competition, load_competitions
from sports_engine.normalization.records import ParsedDataset, SourceMatchRecord, ValidationIssue
from sports_engine.providers.base import DataProvider, DatasetDescriptor, ProviderInfo

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
PARSER_VERSION = "2"


class StatsBombProvider(DataProvider):
    info = ProviderInfo(
        name="statsbomb",
        display_name="StatsBomb Open Data",
        homepage="https://github.com/statsbomb/open-data",
        license_id="StatsBomb-Public-Data-Agreement",
        license_url="https://github.com/statsbomb/open-data/blob/master/LICENSE.pdf",
        terms_url="https://github.com/statsbomb/open-data#terms--conditions",
        attribution="Data: StatsBomb (credit StatsBomb and use their logo when publishing).",
        source_tier=SourceTier.REPUTABLE_STRUCTURED,
        data_classes=(DataClass.POST_MATCH_ONLY, DataClass.NON_POINT_IN_TIME),
        capabilities=("results", "kickoff_times", "events", "xg", "lineups", "managers", "referee", "venue"),
        allowed_hosts=("raw.githubusercontent.com",),
        notes="Sparse season coverage; published long after the matches.",
        restrictions=("attribution required when publishing",),
    )

    def discover(self, competition_ids: Iterable[str], seasons: Iterable[int] | None = None) -> list[DatasetDescriptor]:
        # step 1: the competition index; season files are discovered as follow-ups
        return [DatasetDescriptor(self.name, "competitions", f"{BASE}/competitions.json", "metadata",
                                  competition_id=",".join(sorted(competition_ids)), file_ext="json")]

    def followups(self, descriptor: DatasetDescriptor, content: bytes) -> list[DatasetDescriptor]:
        if descriptor.dataset_key != "competitions":
            if descriptor.kind == "results" and self.settings is not None and self.settings.get("providers.statsbomb.download_events", False):
                matches = json.loads(content.decode("utf-8"))
                return [
                    DatasetDescriptor(self.name, f"events/{m['match_id']}", f"{BASE}/events/{m['match_id']}.json", "events",
                                      competition_id=descriptor.competition_id, season=descriptor.season,
                                      immutable=True, file_ext="json")
                    for m in matches
                ]
            return []
        wanted = [c for c in (descriptor.competition_id or "").split(",") if c]
        by_sb = {get_competition(c).source_code(self.name): c for c in wanted if get_competition(c).source_code(self.name)}
        comps = json.loads(content.decode("utf-8"))
        out = []
        for c in comps:
            if c.get("competition_gender", "male") != "male":
                continue
            cid = by_sb.get(c["competition_id"])
            if cid is None:
                continue
            out.append(
                DatasetDescriptor(
                    self.name,
                    f"matches/{c['competition_id']}/{c['season_id']}",
                    f"{BASE}/matches/{c['competition_id']}/{c['season_id']}.json",
                    "results",
                    competition_id=cid,
                    season=c["season_name"].replace("/", "-"),
                    immutable=True,
                    file_ext="json",
                )
            )
        return out

    def parse(self, descriptor: DatasetDescriptor, content: bytes, raw_sha256: str,
              acquired_at=None) -> ParsedDataset:
        ds = ParsedDataset(self.name, descriptor.dataset_key, raw_sha256, parser_version=PARSER_VERSION)
        if descriptor.kind == "metadata":
            return ds
        try:
            doc = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            ds.issues.append(ValidationIssue("ERROR", "PARSE", str(exc), self.name, descriptor.dataset_key))
            return ds
        if descriptor.kind == "events":
            ds.stat_updates = self._aggregate_events(descriptor, doc)
            return ds
        comp = get_competition(descriptor.competition_id)
        for i, m in enumerate(doc):
            try:
                d = date.fromisoformat(m["match_date"])
                home = m["home_team"]["home_team_name"]
                away = m["away_team"]["away_team_name"]
                hg, ag = m.get("home_score"), m.get("away_score")
                season_name = m["season"]["season_name"]
                start_year = int(season_name[:4])
            except (KeyError, ValueError, TypeError) as exc:
                ds.issues.append(ValidationIssue("ERROR", "PARSE", f"match {i}: {exc}", self.name, descriptor.dataset_key))
                continue
            ko = (m.get("kick_off") or "")[:5] or None
            extra = {
                "statsbomb_match_id": m.get("match_id"),
                "home_managers": [x.get("name") for x in m["home_team"].get("managers", []) or []],
                "away_managers": [x.get("name") for x in m["away_team"].get("managers", []) or []],
                "match_week": m.get("match_week"),
                "stage": (m.get("competition_stage") or {}).get("name"),
            }
            ds.matches.append(
                SourceMatchRecord(
                    source=self.name,
                    source_match_key=f"sb:{m['match_id']}",
                    competition_id=comp.competition_id,
                    season=season_name.replace("/", "-"),
                    season_start_year=start_year,
                    match_date=d,
                    home_team_raw=home,
                    away_team_raw=away,
                    timezone=comp.timezone,
                    kickoff_local_time=ko,
                    kickoff_utc=local_to_utc(d, ko, comp.timezone) if ko else None,
                    # kick_off timezone is inconsistent upstream (winter times +1h vs local slots in
                    # Serie A 2015/16; some look like UTC) -> never treated as an exact kickoff
                    timestamp_quality=TimestampQuality.APPROXIMATE if ko else TimestampQuality.DATE_ONLY,
                    home_goals=int(hg) if hg is not None else None,
                    away_goals=int(ag) if ag is not None else None,
                    status=MatchStatus.FINISHED if hg is not None else MatchStatus.UNKNOWN,
                    venue=(m.get("stadium") or {}).get("name"),
                    referee=(m.get("referee") or {}).get("name"),
                    extra=extra,
                    raw_sha256=raw_sha256,
                    raw_row=i,
                )
            )
        return ds

    @staticmethod
    def _aggregate_events(descriptor: DatasetDescriptor, events: list[dict]) -> dict[str, dict]:
        """Aggregate shots / xG per team from an events file (post-match statistics)."""
        match_id = descriptor.dataset_key.split("/")[-1]
        agg: dict[str, dict[str, float]] = defaultdict(lambda: {"shots": 0, "xg": 0.0, "sot": 0})
        for ev in events:
            if (ev.get("type") or {}).get("name") != "Shot":
                continue
            team = (ev.get("team") or {}).get("name", "?")
            shot = ev.get("shot") or {}
            agg[team]["shots"] += 1
            agg[team]["xg"] += float(shot.get("statsbomb_xg") or 0.0)
            if (shot.get("outcome") or {}).get("name") in ("Goal", "Saved", "Saved To Post"):
                agg[team]["sot"] += 1
        return {f"sb:{match_id}": {"by_team": {k: dict(v) for k, v in agg.items()}}}


def statsbomb_competition_ids() -> dict[str, int]:
    return {cid: c.source_code("statsbomb") for cid, c in load_competitions().items() if c.source_code("statsbomb")}
