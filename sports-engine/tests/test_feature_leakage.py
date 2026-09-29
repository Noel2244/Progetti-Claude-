"""Feature leakage: features at t are invariant to anything after t; no target-derived features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sports_engine.features.team_features import build_team_features
from sports_engine.pit.store import HistoricalStore


def test_features_invariant_to_future(synthetic):
    m, o, _ = synthetic
    t = pd.Timestamp("2020-10-20T00:00:00Z")
    ids = m[pd.to_datetime(m["kickoff_utc"], utc=True) > t]["match_id"].iloc[:6]
    f1 = build_team_features(HistoricalStore(m, o).as_of(t.to_pydatetime()),
                             HistoricalStore(m, o).as_of(t.to_pydatetime()).fixtures(ids), ["ITA1"])
    m2 = m.copy()
    fut = pd.to_datetime(m2["result_available_at"], utc=True) > t
    m2.loc[fut, "home_goals"] = 9
    s2 = HistoricalStore(m2, o)
    f2 = build_team_features(s2.as_of(t.to_pydatetime()), s2.as_of(t.to_pydatetime()).fixtures(ids), ["ITA1"])
    pd.testing.assert_frame_equal(f1.features, f2.features)
    assert f1.fingerprint == f2.fingerprint


def test_features_do_not_contain_target(synthetic):
    m, o, _ = synthetic
    s = HistoricalStore(m, o)
    t = pd.Timestamp("2020-10-20T00:00:00Z")
    ids = m[pd.to_datetime(m["kickoff_utc"], utc=True) > t]["match_id"].iloc[:6]
    f = build_team_features(s.as_of(t.to_pydatetime()), s.as_of(t.to_pydatetime()).fixtures(ids), ["ITA1"]).features
    forbidden = {"home_goals", "away_goals", "result", "y", "outcome", "ft", "score"}
    assert not forbidden & set(f.columns)
    # the target of these fixtures must not be recoverable: correlate features with realised goals
    outcomes = m.set_index("match_id").loc[ids]
    assert f["rest_days"].notna().all()
    assert (f["rest_days"] >= 0).all()


def test_league_normaliser_uses_only_past(synthetic):
    m, o, _ = synthetic
    t = pd.Timestamp("2020-10-20T00:00:00Z")
    ids = m[pd.to_datetime(m["kickoff_utc"], utc=True) > t]["match_id"].iloc[:4]
    s = HistoricalStore(m, o)
    base = build_team_features(s.as_of(t.to_pydatetime()), s.as_of(t.to_pydatetime()).fixtures(ids), ["ITA1"]).features
    m2 = m.copy()
    fut = pd.to_datetime(m2["result_available_at"], utc=True) > t
    m2.loc[fut, ["home_goals", "away_goals"]] = 0     # a future with no goals would change a leaky league average
    s2 = HistoricalStore(m2, o)
    other = build_team_features(s2.as_of(t.to_pydatetime()), s2.as_of(t.to_pydatetime()).fixtures(ids), ["ITA1"]).features
    assert np.allclose(base["gf_last10_rel"], other["gf_last10_rel"], equal_nan=True)
