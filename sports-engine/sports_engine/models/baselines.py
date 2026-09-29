"""Reference baselines that every model must beat.

* ``ClimatologyModel`` - league base rates of H/D/A over a trailing window.
  The minimum bar: a model that cannot beat this knows nothing about teams.
* ``MarketModel``      - margin-removed market consensus at decision time
  (MODEL A in the directive). A model that cannot add information beyond
  this is not promoted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sports_engine.market.consensus import market_view
from sports_engine.models.base import MatchOutcomeModel, MatchPrediction
from sports_engine.pit.store import PITSnapshot


class ClimatologyModel(MatchOutcomeModel):
    name = "climatology"
    version = "1.0"

    def __init__(self, window_days: int = 1825, prior_strength: float = 30.0):
        self.window_days = window_days
        self.prior_strength = prior_strength
        self.p = np.array([0.45, 0.28, 0.27])
        self.n = 0

    def params_dict(self) -> dict:
        return {"window_days": self.window_days, "prior_strength": self.prior_strength}

    def fit(self, snapshot: PITSnapshot, competition_ids: list[str]) -> None:
        since = (pd.Timestamp(snapshot.as_of) - pd.Timedelta(days=self.window_days)).to_pydatetime()
        r = snapshot.results(competition_ids, since=since)
        self.n = len(r)
        if self.n:
            hg, ag = r["home_goals"].to_numpy(), r["away_goals"].to_numpy()
            counts = np.array([(hg > ag).sum(), (hg == ag).sum(), (hg < ag).sum()], dtype=float)
            prior = np.array([0.45, 0.28, 0.27]) * self.prior_strength
            self.p = (counts + prior) / (counts.sum() + self.prior_strength)
        self._fitted_as_of = snapshot.as_of

    def predict(self, fixtures: pd.DataFrame) -> list[MatchPrediction]:
        return [MatchPrediction(r.match_id, self.name, self.version, *map(float, self.p),
                                notes=[f"base rates from {self.n} matches"]) for r in fixtures.itertuples(index=False)]


class MarketModel(MatchOutcomeModel):
    name = "market"
    version = "1.0"

    def __init__(self, method: str = "power", max_staleness_hours: float = 72.0):
        self.method = method
        self.max_staleness_hours = max_staleness_hours
        self._snapshot: PITSnapshot | None = None

    def params_dict(self) -> dict:
        return {"method": self.method}

    def fit(self, snapshot: PITSnapshot, competition_ids: list[str]) -> None:
        self._snapshot = snapshot
        self._fitted_as_of = snapshot.as_of

    def predict(self, fixtures: pd.DataFrame) -> list[MatchPrediction]:
        if self._snapshot is None:
            return []
        out = []
        for r in fixtures.itertuples(index=False):
            odds = self._snapshot.match_odds(r.match_id, "1X2")
            mv = market_view(odds, r.match_id, "1X2", method=self.method, as_of=self._snapshot.as_of,
                             max_staleness_hours=self.max_staleness_hours)
            if mv.consensus is None:
                continue
            ph, pd_, pa = map(float, mv.consensus)
            interval = None
            if mv.dispersion is not None:
                interval = {k: (max(0.0, float(mv.consensus[i] - 1.645 * mv.dispersion[i])),
                                min(1.0, float(mv.consensus[i] + 1.645 * mv.dispersion[i]))) for i, k in enumerate("HDA")}
            out.append(MatchPrediction(r.match_id, self.name, self.version, ph, pd_, pa, interval=interval,
                                       notes=[f"{mv.n_books} books, margin {mv.margin_median:.3f}, {self.method}"] + mv.flags))
        return out
