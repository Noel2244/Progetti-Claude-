from __future__ import annotations

import numpy as np
import pandas as pd

from sports_engine.quality.drift import calibration_drift, league_drift, performance_drift


def _results(n, p_home, p_draw, goals, seed, start=0):
    rng = np.random.default_rng(seed)
    u = rng.uniform(size=n)
    hg = np.where(u < p_home, 2, np.where(u < p_home + p_draw, 1, 0))
    ag = np.where(u < p_home, 0, np.where(u < p_home + p_draw, 1, 2))
    extra = rng.poisson(max(goals - 2.0, 0.01), n)
    return pd.DataFrame({"home_goals": hg + extra, "away_goals": ag,
                         "result_available_at": pd.date_range("2000-01-01", periods=n, freq="D", tz="UTC") + pd.Timedelta(days=start)})


def test_no_drift_when_stable():
    r = pd.concat([_results(1900, .45, .27, 2.6, 1), _results(380, .45, .27, 2.6, 2, 1900)])
    res = {x.metric: x for x in league_drift(r, "league:X")}
    assert all(x.status in ("OK", "WARN") for x in res.values())


def test_detects_regime_shift():
    # e.g. matches without crowds: home advantage collapses
    r = pd.concat([_results(1900, .46, .27, 2.6, 1), _results(380, .30, .27, 2.6, 2, 1900)])
    res = {x.metric: x for x in league_drift(r, "league:X")}
    assert res["home_win_rate"].status == "ALERT" and res["home_win_rate"].action == "RETRAIN"


def test_small_samples_never_alarm():
    rng = np.random.default_rng(0)
    assert performance_drift(rng.uniform(1.5, 2.0, 20), 0.98, "p").status == "INSUFFICIENT_SAMPLE"
    assert calibration_drift(np.full(30, 0.5), np.ones(30), "p").status == "INSUFFICIENT_SAMPLE"


def test_performance_and_calibration_drift_detected():
    rng = np.random.default_rng(3)
    worse = rng.normal(1.10, 0.4, 600)                 # live log loss far above the backtest's 0.98
    assert performance_drift(worse, 0.98, "p").status == "ALERT"
    ok = rng.normal(0.98, 0.4, 600)
    assert performance_drift(ok, 0.98, "p").status in ("OK", "WARN")
    p = np.full(800, 0.30)
    obs = (rng.uniform(size=800) < 0.40).astype(float)  # event happens far more often than predicted
    assert calibration_drift(p, obs, "p").status == "ALERT"
