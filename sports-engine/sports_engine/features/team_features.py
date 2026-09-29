"""Point-in-time team features (versioned).

Every feature is computed from a ``PITSnapshot`` only, so it can never contain
information from after the snapshot's ``as_of``. League-level normalisers (e.g.
average goals) are computed from the same snapshot - never from the full data.

FEATURE_VERSION must change whenever a definition changes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sports_engine.core.hashing import stable_hash
from sports_engine.pit.store import PITSnapshot

FEATURE_VERSION = "team-form-v1"


@dataclass
class FeatureSnapshot:
    as_of: str
    feature_version: str
    snapshot_fingerprint: str
    features: pd.DataFrame          # one row per (match_id, side)

    @property
    def fingerprint(self) -> str:
        return stable_hash([self.feature_version, self.snapshot_fingerprint,
                            self.features.round(8).to_dict("records")], 16)


def _team_long(results: pd.DataFrame) -> pd.DataFrame:
    h = pd.DataFrame({"team": results["home_team_id"], "opp": results["away_team_id"], "gf": results["home_goals"],
                      "ga": results["away_goals"], "home": 1, "date": pd.to_datetime(results["match_date"]),
                      "competition_id": results["competition_id"], "season": results["season_start_year"]})
    a = pd.DataFrame({"team": results["away_team_id"], "opp": results["home_team_id"], "gf": results["away_goals"],
                      "ga": results["home_goals"], "home": 0, "date": pd.to_datetime(results["match_date"]),
                      "competition_id": results["competition_id"], "season": results["season_start_year"]})
    long = pd.concat([h, a], ignore_index=True)
    long["pts"] = np.where(long.gf > long.ga, 3, np.where(long.gf == long.ga, 1, 0))
    return long.sort_values("date", kind="mergesort")


def build_team_features(snapshot: PITSnapshot, fixtures: pd.DataFrame, competitions: list[str] | None = None) -> FeatureSnapshot:
    res = snapshot.results(competitions=None)         # rest/congestion use every competition we know about
    long = _team_long(res) if len(res) else pd.DataFrame(columns=["team", "date", "gf", "ga", "pts", "home", "competition_id", "season"])
    league = res if not competitions else res[res["competition_id"].isin(competitions)]
    as_of = pd.Timestamp(snapshot.as_of).tz_convert(None)
    recent = league[pd.to_datetime(league["match_date"]) > as_of - pd.Timedelta(days=730)] if len(league) else league
    lg_goals = float((recent["home_goals"].mean() + recent["away_goals"].mean()) / 2) if len(recent) else np.nan
    rows = []
    for fx in fixtures.itertuples(index=False):
        season = int(fx.season_start_year)
        for side, team in (("home", fx.home_team_id), ("away", fx.away_team_id)):
            t = long[long["team"] == team] if len(long) else long
            lt = t[t["competition_id"] == fx.competition_id] if len(t) else t
            last5, last10 = lt.tail(5), lt.tail(10)
            prev_season = lt[lt["season"] == season - 1]
            rows.append({
                "match_id": fx.match_id, "side": side, "team": team,
                "matches_365d": int((t["date"] > as_of - pd.Timedelta(days=365)).sum()) if len(t) else 0,
                "ppg_last5": float(last5["pts"].mean()) if len(last5) else np.nan,
                "gf_last10": float(last10["gf"].mean()) if len(last10) else np.nan,
                "ga_last10": float(last10["ga"].mean()) if len(last10) else np.nan,
                "gf_last10_rel": float(last10["gf"].mean() / lg_goals) if len(last10) and lg_goals else np.nan,
                "rest_days": float((as_of - t["date"].max()).days) if len(t) else np.nan,
                "matches_last_14d": int((t["date"] > as_of - pd.Timedelta(days=14)).sum()) if len(t) else 0,
                "promoted": int(len(lt) > 0 and len(prev_season) == 0 and (lt["season"] < season).any()),
                "new_to_competition": int(len(lt) == 0),
            })
    return FeatureSnapshot(str(snapshot.as_of), FEATURE_VERSION, snapshot.fingerprint, pd.DataFrame(rows))
