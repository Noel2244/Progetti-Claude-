"""Nested walk-forward hyper-parameter selection (directive section 57).

OUTER loop over test seasons s:
    INNER loop: every candidate configuration is evaluated by a walk-forward on the
    ``inner_seasons`` seasons immediately before s (all data < start of season s);
    the candidate with the lowest inner log loss is selected;
    the selected configuration then predicts season s (walk-forward, point-in-time).

The outer predictions are therefore never used to choose anything. The total number
of evaluated configurations is returned so it can be registered for multiple-testing
accounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from sports_engine.backtesting.walkforward import BacktestConfig, WalkForwardBacktest
from sports_engine.calibration.metrics import log_loss_per_obs
from sports_engine.pit.store import HistoricalStore


@dataclass
class NestedResult:
    model: str
    grid: list[dict]
    per_season: list[dict] = field(default_factory=list)
    outer_predictions: pd.DataFrame | None = None
    n_candidates_evaluated: int = 0

    @property
    def outer_logloss(self) -> float:
        p = self.outer_predictions
        return float(log_loss_per_obs(p[["p_H", "p_D", "p_A"]].to_numpy(), p["y"].to_numpy()).mean())


def _season_window(start_year: int, n: int = 1) -> tuple[date, date]:
    return date(start_year, 7, 1), date(start_year + n, 7, 1) - timedelta(days=1)


def _run(store, competitions, model, factories, start, end, refit_days) -> pd.DataFrame:
    cfg = BacktestConfig(competitions=competitions, test_start=start, test_end=end, models=[model],
                         calibrate=False, bootstrap=0, refit_days=refit_days)
    bt = WalkForwardBacktest(store, cfg, factories)
    sched = bt._schedule()
    if sched.empty:
        return pd.DataFrame()
    preds = bt._predict_all(sched)
    out = store.outcomes(sched["match_id"])
    y = np.where(out["home_goals"] > out["away_goals"], 0, np.where(out["home_goals"] == out["away_goals"], 1, 2))
    preds = preds.merge(pd.DataFrame({"match_id": out["match_id"].to_numpy(), "y": y,
                                      "disputed": out["score_disputed"].to_numpy()}), on="match_id")
    return preds[preds["disputed"] == 0]


def nested_walk_forward(store: HistoricalStore, competitions: list[str], model: str, grid: list[dict],
                        factories_for, outer_seasons: list[int], inner_seasons: int = 2,
                        refit_days_inner: int = 14, refit_days_outer: int = 7) -> NestedResult:
    """``factories_for(params) -> dict[name, factory]`` builds models for one configuration."""
    res = NestedResult(model=model, grid=grid)
    outer_frames = []
    for s in outer_seasons:
        inner_start, _ = _season_window(s - inner_seasons)
        inner_end = date(s, 7, 1) - timedelta(days=1)          # strictly before the outer season
        scores = []
        for params in grid:
            p = _run(store, competitions, model, factories_for(params), inner_start, inner_end, refit_days_inner)
            res.n_candidates_evaluated += 1
            ll = float(log_loss_per_obs(p[["p_H", "p_D", "p_A"]].to_numpy(), p["y"].to_numpy()).mean()) if len(p) else np.inf
            scores.append(ll)
        best = int(np.argmin(scores))
        o_start, o_end = _season_window(s)
        outer = _run(store, competitions, model, factories_for(grid[best]), o_start, o_end, refit_days_outer)
        outer["outer_season"] = s
        outer_frames.append(outer)
        res.per_season.append({"season": s, "inner_window": f"{inner_start}..{inner_end}", "inner_logloss": scores,
                               "chosen": grid[best], "outer_n": int(len(outer)),
                               "outer_logloss": float(log_loss_per_obs(outer[["p_H", "p_D", "p_A"]].to_numpy(),
                                                                       outer["y"].to_numpy()).mean()) if len(outer) else None})
    res.outer_predictions = pd.concat(outer_frames, ignore_index=True) if outer_frames else pd.DataFrame()
    return res
