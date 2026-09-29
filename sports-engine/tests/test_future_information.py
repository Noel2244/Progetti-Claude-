"""Future information guards: closing odds, decision times, holdout, disputed results."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from sports_engine.backtesting.walkforward import BacktestConfig, WalkForwardBacktest
from sports_engine.core.errors import HoldoutAccessError
from sports_engine.models.registry import model_factories
from sports_engine.pit.store import HistoricalStore


@pytest.fixture(scope="module")
def small_result():
    from sports_engine.research_lab.simulate import simulate_league
    m, o, _ = simulate_league(n_teams=8, seasons=4, start_year=2016, seed=5, market="efficient")
    store = HistoricalStore(m, o)
    cfg = BacktestConfig(competitions=["ITA1"], test_start=date(2018, 7, 1), test_end=date(2020, 7, 1),
                         burn_in_start=date(2017, 7, 1), models=["climatology", "elo", "dixon_coles", "market"],
                         calibration_min_train=50, bootstrap=100)
    return m, o, store, WalkForwardBacktest(store, cfg, model_factories()).run()


def test_every_prediction_made_before_kickoff(small_result):
    m, _, _, res = small_result
    ko = pd.to_datetime(m.set_index("match_id")["kickoff_utc"], utc=True)
    p = res.predictions
    assert (p["decision_time"] < ko.reindex(p["match_id"]).to_numpy()).all()
    assert (p["model_fitted_as_of"] <= p["decision_time"]).all()


def test_market_model_never_uses_closing_odds(small_result):
    m, o, store, res = small_result
    mk = res.predictions[res.predictions["model"] == "market"].set_index("match_id")
    close = o[o["snapshot_type"] == "CLOSING"]
    # reconstruct the consensus from CLOSING prices: it must differ from what the model used
    from sports_engine.market.consensus import market_view
    diffs = []
    for mid in mk.index[:40]:
        mv = market_view(close, mid, "1X2")
        diffs.append(abs(mv.consensus[0] - mk.loc[mid, "p_H"]))
    assert max(diffs) > 1e-6


def test_holdout_is_clipped_unless_requested():
    from sports_engine.research_lab.simulate import simulate_league
    m, o, _ = simulate_league(n_teams=6, seasons=3, start_year=2016, seed=2, market=None)
    store = HistoricalStore(m, o)
    cfg = BacktestConfig(competitions=["ITA1"], test_start=date(2017, 7, 1), test_end=date(2019, 7, 1),
                         holdout_start=date(2018, 7, 1), models=["climatology"], calibrate=False, bootstrap=50)
    res = WalkForwardBacktest(store, cfg, model_factories()).run()
    dts = pd.to_datetime(m.set_index("match_id").loc[res.predictions["match_id"], "match_date"])
    assert dts.max() < pd.Timestamp("2018-07-01")
    assert any("holdout" in n for n in res.notes)
    with pytest.raises(HoldoutAccessError):
        cfg2 = BacktestConfig(competitions=["ITA1"], test_start=date(2017, 7, 1), test_end=date(2019, 7, 1),
                              holdout_start=None, use_holdout=True, models=["climatology"])
        WalkForwardBacktest(store, cfg2, model_factories()).run()


def test_calibration_uses_only_prior_seasons(small_result):
    _, _, _, res = small_result
    for model, seasons in res.calibration.items():
        first = min(seasons)
        assert seasons[first]["method"] == "identity"     # nothing earlier to learn from


def test_disputed_scores_excluded_from_training(synthetic):
    m, o, _ = synthetic
    m2 = m.copy()
    m2["score_disputed"] = 0
    idx = m2.index[5]
    m2.loc[idx, ["home_goals", "away_goals", "score_disputed"]] = [9, 0, 1]
    t = pd.Timestamp("2020-06-01T00:00:00Z")
    snap = HistoricalStore(m2, o).as_of(t.to_pydatetime())
    assert m2.loc[idx, "match_id"] not in set(snap.results(exclude_disputed=True)["match_id"])
