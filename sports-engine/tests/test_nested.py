from __future__ import annotations

import numpy as np
import pandas as pd

from sports_engine.backtesting.nested import nested_walk_forward
from sports_engine.models.registry import model_factories
from sports_engine.pit.store import HistoricalStore
from sports_engine.research_lab.simulate import simulate_league


def _factories(params):
    return model_factories(overrides={"dixon_coles": params})


def test_nested_selection_uses_only_prior_seasons():
    m, _, _ = simulate_league(n_teams=8, seasons=5, start_year=2015, seed=4, market=None)
    grid = [{"xi_per_day": 0.0, "uncertainty": False}, {"xi_per_day": 0.004, "uncertainty": False}]
    res = nested_walk_forward(HistoricalStore(m), ["ITA1"], "dixon_coles", grid, _factories, outer_seasons=[2018, 2019],
                              inner_seasons=2)
    assert res.n_candidates_evaluated == 4
    assert {r["season"] for r in res.per_season} == {2018, 2019}
    assert np.isfinite(res.outer_logloss)
    # changing the OUTER seasons' results must not change which configuration the inner loop chose
    m2 = m.copy()
    outer = m2["season_start_year"] >= 2018
    m2.loc[outer, ["home_goals", "away_goals"]] = m2.loc[outer, ["away_goals", "home_goals"]].to_numpy()
    res2 = nested_walk_forward(HistoricalStore(m2), ["ITA1"], "dixon_coles", grid, _factories, outer_seasons=[2018],
                               inner_seasons=2)
    assert res2.per_season[0]["chosen"] == res.per_season[0]["chosen"]
    assert res2.per_season[0]["inner_logloss"] == res.per_season[0]["inner_logloss"]
