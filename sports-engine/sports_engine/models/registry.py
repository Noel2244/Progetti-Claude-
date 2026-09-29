"""Model factories built from configuration. Adding a model = adding a factory here."""

from __future__ import annotations

from typing import Callable

from sports_engine.models.base import MatchOutcomeModel
from sports_engine.models.baselines import ClimatologyModel, MarketModel
from sports_engine.models.elo import EloModel, EloParams
from sports_engine.models.goals import GoalModel, GoalModelParams

STATISTICAL_MODELS = ("elo", "poisson", "poisson_weighted", "dixon_coles")


def model_factories(settings=None, overrides: dict | None = None) -> dict[str, Callable[[], MatchOutcomeModel]]:
    cfg = (settings.get("models", {}) if settings is not None else {}) or {}
    overrides = overrides or {}

    def pick(section: str, cls) -> dict:
        d = dict(cfg.get(section, {}) or {})
        d.update(overrides.get(section, {}))
        return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}

    elo_kw = pick("elo", EloParams)
    pois_kw = pick("poisson", GoalModelParams)
    dc_kw = pick("dixon_coles", GoalModelParams)
    margin = (settings.get("decision.margin_method", "power") if settings is not None else "power")
    return {
        "climatology": lambda: ClimatologyModel(),
        "market": lambda: MarketModel(method=margin),
        "elo": lambda: EloModel(EloParams(**elo_kw)),
        "poisson": lambda: GoalModel(GoalModelParams(**{**pois_kw, "xi_per_day": 0.0, "dixon_coles": False}), name="poisson"),
        "poisson_weighted": lambda: GoalModel(GoalModelParams(**{**pois_kw, "dixon_coles": False}), name="poisson_weighted"),
        "dixon_coles": lambda: GoalModel(GoalModelParams(**{**dc_kw, "dixon_coles": True}), name="dixon_coles"),
    }
