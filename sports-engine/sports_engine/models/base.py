"""Model interface. Models only ever see a ``PITSnapshot`` - never the full store."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sports_engine.pit.store import PITSnapshot


@dataclass
class MatchPrediction:
    match_id: str
    model: str
    model_version: str
    p_home: float
    p_draw: float
    p_away: float
    lambda_home: float | None = None
    lambda_away: float | None = None
    rho: float = 0.0
    matrix: np.ndarray | None = None
    # uncertainty: 5th / 95th percentile of each 1X2 probability, where available
    interval: dict[str, tuple[float, float]] | None = None
    sd: dict[str, float] | None = None
    home_matches: int | None = None     # team history available to the model
    away_matches: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def probs(self) -> np.ndarray:
        return np.array([self.p_home, self.p_draw, self.p_away])

    def validate(self) -> None:
        p = self.probs
        if not np.all(np.isfinite(p)) or np.any(p < 0) or np.any(p > 1) or abs(p.sum() - 1) > 1e-6:
            raise ValueError(f"invalid probabilities for {self.match_id}: {p}")


class MatchOutcomeModel(ABC):
    name: str = "base"
    version: str = "0"

    @abstractmethod
    def fit(self, snapshot: PITSnapshot, competition_ids: list[str]) -> None:
        """Fit using only information visible in ``snapshot``."""

    @abstractmethod
    def predict(self, fixtures: pd.DataFrame) -> list[MatchPrediction]:
        """Predict fixtures (schedule rows only; no results)."""

    @property
    def fitted_as_of(self):
        return getattr(self, "_fitted_as_of", None)

    def params_dict(self) -> dict:
        return {}
