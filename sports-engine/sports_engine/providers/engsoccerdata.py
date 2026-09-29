"""engsoccerdata (James Curley) - long-term historical results.

* Repository: https://github.com/jalapic/engsoccerdata
* License: GPL (>= 2) R package; README: free for non-commercial use, citation requested.
* Coverage: England 1888-, Italy 1929-, Spain 1929-, Germany 1963-, France 1932-, ...
* Results only (no odds, no kickoff times) -> DATE_ONLY timestamps, LONG_TERM.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Iterable

import pandas as pd

from sports_engine.core.enums import DataClass, MatchStatus, SourceTier, TimestampQuality
from sports_engine.entity.competitions import get_competition, season_label
from sports_engine.normalization.records import ParsedDataset, SourceMatchRecord, ValidationIssue
from sports_engine.providers.base import DataProvider, DatasetDescriptor, ProviderInfo

BASE_URL = "https://raw.githubusercontent.com/jalapic/engsoccerdata/master/data-raw/{file}.csv"
PARSER_VERSION = "1"


class EngSoccerDataProvider(DataProvider):
    info = ProviderInfo(
        name="engsoccerdata",
        display_name="engsoccerdata (J. Curley)",
        homepage="https://github.com/jalapic/engsoccerdata",
        license_id="GPL-2.0-or-later",
        license_url="https://github.com/jalapic/engsoccerdata/blob/master/DESCRIPTION",
        terms_url="https://github.com/jalapic/engsoccerdata#readme",
        attribution="James P. Curley (2016). engsoccerdata: English Soccer Data 1871-2016.",
        source_tier=SourceTier.SECONDARY,
        data_classes=(DataClass.LONG_TERM, DataClass.POINT_IN_TIME_READY),
        capabilities=("results",),
        allowed_hosts=("raw.githubusercontent.com",),
        notes="Results only; dates without kickoff times; season = start year. "
        "European leagues are updated less frequently than England.",
        restrictions=("non-commercial use", "cite the package"),
    )

    def discover(self, competition_ids: Iterable[str], seasons: Iterable[int] | None = None) -> list[DatasetDescriptor]:
        files: dict[str, list[str]] = {}
        for cid in competition_ids:
            code = get_competition(cid).source_code(self.name)
            if code:
                files.setdefault(code["file"], []).append(cid)
        return [
            DatasetDescriptor(
                provider=self.name,
                dataset_key=f"{file}",
                url=BASE_URL.format(file=file),
                kind="results",
                competition_id=",".join(sorted(cids)),
                immutable=False,  # the file is revised upstream; every revision is kept
                file_ext="csv",
            )
            for file, cids in sorted(files.items())
        ]

    def parse(self, descriptor: DatasetDescriptor, content: bytes, raw_sha256: str,
              acquired_at=None) -> ParsedDataset:
        ds = ParsedDataset(self.name, descriptor.dataset_key, raw_sha256, parser_version=PARSER_VERSION)
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
        df.columns = [c.strip() for c in df.columns]
        required = {"Date", "Season", "home", "visitor", "hgoal", "vgoal"}
        missing = required - set(df.columns)
        if missing:
            ds.issues.append(ValidationIssue("ERROR", "SCHEMA", f"missing columns {sorted(missing)}", self.name, descriptor.dataset_key))
            return ds
        wanted = [c for c in (descriptor.competition_id or "").split(",") if c]
        tier_map: dict[str, str] = {}
        for cid in wanted:
            code = get_competition(cid).source_code(self.name) or {}
            if code.get("file") == descriptor.dataset_key:
                tier_map[str(code.get("tier", ""))] = cid
        seen: dict[str, int] = {}
        for i, row in enumerate(df.to_dict("records")):
            tier = str(row.get("tier", "")).strip()
            cid = tier_map.get(tier) if "tier" in df.columns else (next(iter(tier_map.values()), None))
            if cid is None:
                continue
            comp = get_competition(cid)
            try:
                d = date.fromisoformat(row["Date"].strip())
                start_year = int(row["Season"])
                hg, ag = int(row["hgoal"]), int(row["vgoal"])
            except (ValueError, TypeError) as exc:
                ds.issues.append(ValidationIssue("ERROR", "PARSE", f"row {i}: {exc}", self.name, descriptor.dataset_key))
                continue
            home, away = row["home"].strip(), row["visitor"].strip()
            base_key = f"{descriptor.dataset_key}:{cid}:{d.isoformat()}:{home}:{away}"
            n = seen.get(base_key, 0)
            seen[base_key] = n + 1
            key = base_key if n == 0 else f"{base_key}#{n}"
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
                    timezone=comp.timezone,
                    timestamp_quality=TimestampQuality.DATE_ONLY,
                    home_goals=hg,
                    away_goals=ag,
                    status=MatchStatus.FINISHED,
                    raw_sha256=raw_sha256,
                    raw_row=i,
                )
            )
        return ds
