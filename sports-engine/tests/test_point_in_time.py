"""as_of(timestamp) semantics of the point-in-time store."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from sports_engine.core.errors import LeakageError
from sports_engine.pit.cutoffs import DecisionTimingPolicy
from sports_engine.pit.store import HistoricalStore


def test_results_only_visible_after_availability(store, synthetic):
    m, _, _ = synthetic
    row = m.iloc[50]
    avail = pd.Timestamp(row["result_available_at"])
    before = store.as_of((avail - timedelta(seconds=1)).to_pydatetime())
    at = store.as_of(avail.to_pydatetime())
    assert row["match_id"] not in set(before.results()["match_id"])
    assert row["match_id"] in set(at.results()["match_id"])       # "<= as_of" is inclusive


def test_results_never_after_as_of(store):
    for t in pd.date_range("2019-09-01", "2021-05-01", freq="37D", tz="UTC"):
        snap = store.as_of(t.to_pydatetime())
        r = snap.results()
        assert (r["result_available_at"] <= t).all()
        snap.assert_no_future(r, "result_available_at")


def test_fixture_view_has_no_result_columns_and_neutral_status(store, synthetic):
    m, _, _ = synthetic
    future_ids = m["match_id"].iloc[-5:]
    snap = store.as_of(datetime(2019, 9, 1, tzinfo=timezone.utc))
    fx = snap.fixtures(future_ids)
    for col in ("home_goals", "away_goals", "result_available_at"):
        assert col not in fx.columns
    assert set(fx["status"]) == {"SCHEDULED"}


def test_odds_visibility_and_closing_hidden_before_kickoff(store, synthetic):
    m, o, _ = synthetic
    mid = m["match_id"].iloc[100]
    ko = pd.Timestamp(m.set_index("match_id").loc[mid, "kickoff_utc"])
    snap = store.as_of((ko - timedelta(hours=1)).to_pydatetime())
    visible = snap.match_odds(mid)
    assert len(visible) > 0
    assert (visible["snapshot_type"] != "CLOSING").all()
    assert (pd.to_datetime(visible["available_at"], utc=True) <= ko - timedelta(hours=1)).all()
    snap_after = store.as_of(ko.to_pydatetime())
    assert (snap_after.match_odds(mid)["snapshot_type"] == "CLOSING").any()


def test_assert_no_future_raises():
    m = pd.DataFrame([{"match_id": "x", "competition_id": "ITA1", "season": "2020-2021", "season_start_year": 2020,
                       "match_date": "2020-09-20", "kickoff_utc": "2020-09-20T13:00:00+00:00", "kickoff_time_known": 1,
                       "timestamp_quality": "EXACT", "home_team_id": "a", "away_team_id": "b", "home_goals": 1,
                       "away_goals": 0, "status": "FINISHED", "result_available_at": "2020-09-20T16:00:00+00:00"}])
    s = HistoricalStore(m)
    snap = s.as_of(datetime(2020, 9, 20, 12, tzinfo=timezone.utc))
    with pytest.raises(LeakageError):
        snap.assert_no_future(pd.DataFrame({"t": ["2020-09-21T00:00:00Z"]}), "t")


def test_fingerprint_changes_with_visible_data(store, synthetic):
    m, _, _ = synthetic
    t1 = pd.Timestamp(m["result_available_at"].iloc[30])
    a = store.as_of(t1.to_pydatetime()).fingerprint
    b = store.as_of((t1 + timedelta(days=30)).to_pydatetime()).fingerprint
    c = store.as_of(t1.to_pydatetime()).fingerprint
    assert a != b and a == c


def test_decision_policy_cutoffs_before_kickoff():
    pol = DecisionTimingPolicy(60)
    ko = datetime(2024, 3, 2, 19, 45, tzinfo=timezone.utc)
    c = pol.cutoffs(ko, date(2024, 3, 2), "Europe/Rome", [ko - timedelta(hours=30), ko - timedelta(minutes=10)])
    assert c.policy == "at_latest_prematch_odds"
    assert c.prediction_timestamp == ko - timedelta(hours=30)       # the 10-min snapshot is inside the lead window
    assert c.feature_cutoff <= c.prediction_timestamp < ko
    c2 = pol.cutoffs(None, date(2010, 3, 2), "Europe/Rome", None)
    assert c2.policy == "start_of_match_day"
    assert c2.prediction_timestamp == datetime(2010, 3, 1, 23, 0, tzinfo=timezone.utc)
