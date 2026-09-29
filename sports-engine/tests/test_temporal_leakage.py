"""Temporal leakage: predictions must not change when the FUTURE changes.

"Canary" method: take a decision time t, randomly alter every result and every
odds snapshot that becomes available after t, rebuild the store, and require the
predictions made at t to be bit-for-bit identical.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sports_engine.models.registry import model_factories
from sports_engine.pit.store import HistoricalStore


def _perturb_future(m: pd.DataFrame, o: pd.DataFrame, t: pd.Timestamp, seed: int = 0):
    rng = np.random.default_rng(seed)
    m2, o2 = m.copy(), o.copy()
    fut = pd.to_datetime(m2["result_available_at"], utc=True) > t
    m2.loc[fut, "home_goals"] = rng.integers(0, 7, fut.sum())
    m2.loc[fut, "away_goals"] = rng.integers(0, 7, fut.sum())
    fo = pd.to_datetime(o2["available_at"], utc=True) > t
    o2.loc[fo, "odds"] = np.round(rng.uniform(1.05, 20, fo.sum()), 2)
    return m2, o2


def _predict(store: HistoricalStore, t: pd.Timestamp, ids, names):
    snap = store.as_of(t.to_pydatetime())
    fx = snap.fixtures(ids)
    out = {}
    for name in names:
        model = model_factories()[name]()
        model.fit(snap, ["ITA1"])
        out[name] = {p.match_id: (p.p_home, p.p_draw, p.p_away) for p in model.predict(fx)}
    return out


def test_future_results_and_odds_do_not_change_predictions(synthetic):
    m, o, _ = synthetic
    t = pd.Timestamp("2020-11-15T00:00:00Z")
    ids = m[pd.to_datetime(m["kickoff_utc"], utc=True) > t + pd.Timedelta(days=2)]["match_id"].iloc[:8]
    names = ["climatology", "elo", "poisson", "poisson_weighted", "dixon_coles", "market"]
    a = _predict(HistoricalStore(m, o), t, ids, names)
    m2, o2 = _perturb_future(m, o, t)
    b = _predict(HistoricalStore(m2, o2), t, ids, names)
    for name in names:
        assert a[name] == b[name], f"{name} predictions changed when only the future changed"


def test_shuffled_row_order_does_not_change_predictions(synthetic):
    m, o, _ = synthetic
    t = pd.Timestamp("2020-11-15T00:00:00Z")
    ids = m[pd.to_datetime(m["kickoff_utc"], utc=True) > t]["match_id"].iloc[:5]
    a = _predict(HistoricalStore(m, o), t, ids, ["elo", "dixon_coles"])
    b = _predict(HistoricalStore(m.sample(frac=1, random_state=1), o.sample(frac=1, random_state=2)), t, ids, ["elo", "dixon_coles"])
    for name in a:
        for k in a[name]:
            assert np.allclose(a[name][k], b[name][k], atol=1e-6)


def test_elo_incremental_equals_from_scratch(synthetic):
    """Incremental walk-forward updates must equal a fresh fit at the same as_of."""
    m, o, _ = synthetic
    store = HistoricalStore(m, o)
    inc = model_factories()["elo"]()
    end = pd.Timestamp("2020-12-01", tz="UTC")
    for t in list(pd.date_range(pd.Timestamp("2019-10-01", tz="UTC"), end, freq="30D")) + [end]:
        inc.fit(store.as_of(t.to_pydatetime()), ["ITA1"])
    fresh = model_factories()["elo"]()
    fresh.fit(store.as_of(end.to_pydatetime()), ["ITA1"])
    assert inc.fitted_as_of == fresh.fitted_as_of
    for team in fresh.ratings:
        assert abs(inc.ratings[team] - fresh.ratings[team]) < 1e-9
