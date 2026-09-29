from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings as hsettings
from hypothesis import strategies as st

from sports_engine.market.clv import clv_fair, clv_price
from sports_engine.market.consensus import market_view
from sports_engine.market.margin import METHODS, implied, remove_margin

odds3 = st.lists(st.floats(min_value=1.05, max_value=30.0), min_size=3, max_size=3)


def test_multiplicative_known_values():
    fp = remove_margin([2.0, 3.5, 4.0], "multiplicative")
    raw = np.array([0.5, 1 / 3.5, 0.25])
    assert fp.margin == pytest.approx(raw.sum() - 1)
    assert np.allclose(fp.fair, raw / raw.sum())


@hsettings(max_examples=200, deadline=None)
@given(odds3)
def test_fair_probabilities_are_valid(o):
    pi = 1 / np.array(o)
    for method in METHODS:
        try:
            fp = remove_margin(o, method)
        except ValueError:
            assert method == "additive"   # additive may legitimately fail for long shots
            continue
        assert np.all(fp.fair >= 0) and np.all(fp.fair <= 1)
        assert fp.fair.sum() == pytest.approx(1.0, abs=1e-9)
        if pi.sum() > 1:
            # order of outcomes is preserved (shorter odds -> higher probability)
            assert np.array_equal(np.argsort(o, kind="stable"), np.argsort(-fp.fair, kind="stable")) or len(set(o)) < 3


def test_power_and_shin_shift_probability_toward_favourite():
    o = [1.4, 4.6, 8.5]
    mult = remove_margin(o, "multiplicative").fair
    for m in ("power", "shin", "odds_ratio"):
        f = remove_margin(o, m).fair
        assert f[0] > mult[0] and f[2] < mult[2]     # favourite-longshot bias correction


def test_invalid_odds_rejected():
    with pytest.raises(ValueError):
        implied([1.0, 2.0])
    with pytest.raises(ValueError):
        implied([2.0])


def test_clv():
    assert clv_price(2.2, 2.0) == pytest.approx(0.1)
    assert clv_fair(2.2, 0.5) == pytest.approx(0.1)
    with pytest.raises(ValueError):
        clv_price(1.0, 2.0)


def _odds_rows(mid, books, t="2024-01-01T10:00:00Z"):
    rows = []
    for b, prices in books.items():
        for sel, p in zip("HDA", prices):
            rows.append({"match_id": mid, "bookmaker": b, "market": "1X2", "selection": sel, "line": np.nan,
                         "odds": p, "available_at": t, "snapshot_type": "PRE_MATCH", "is_aggregate": 0})
    return pd.DataFrame(rows)


def test_consensus_median_best_price_and_outlier_flag():
    df = _odds_rows("m1", {"a": [2.0, 3.4, 4.0], "b": [2.05, 3.3, 3.9], "c": [1.95, 3.5, 4.1], "d": [3.2, 3.4, 2.6]})
    mv = market_view(df, "m1", "1X2", method="multiplicative")
    assert mv.n_books == 4
    assert mv.consensus.sum() == pytest.approx(1.0)
    assert mv.best("H") == (3.2, "d")
    assert any(f.startswith("OUTLIER_BEST_PRICE:H:d") for f in mv.flags)


def test_stale_and_missing():
    df = _odds_rows("m1", {"a": [2.0, 3.4, 4.0]}, t="2024-01-01T10:00:00Z")
    mv = market_view(df, "m1", "1X2", as_of=pd.Timestamp("2024-01-10T10:00:00Z").to_pydatetime(), max_staleness_hours=72)
    assert "STALE_ODDS" in mv.flags and "SINGLE_BOOK" in mv.flags
    assert market_view(df, "zzz", "1X2").flags == ["NO_ODDS"]
    inc = df[df["selection"] != "A"]
    assert market_view(inc, "m1", "1X2").flags == ["INCOMPLETE_MARKET"]


def test_aggregates_excluded_when_books_exist():
    df = _odds_rows("m1", {"a": [2.0, 3.4, 4.0], "b": [2.1, 3.3, 3.8]})
    agg = _odds_rows("m1", {"agg_max": [9.0, 9.0, 9.0]})
    agg["is_aggregate"] = 1
    mv = market_view(pd.concat([df, agg]), "m1", "1X2")
    assert mv.n_books == 2 and mv.best("H")[1] != "agg_max"
