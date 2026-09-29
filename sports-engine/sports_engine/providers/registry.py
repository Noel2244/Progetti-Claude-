"""Provider registry. Adding a provider = adding an adapter here; the core is unchanged."""

from __future__ import annotations

from sports_engine.providers.base import DataProvider
from sports_engine.providers.engsoccerdata import EngSoccerDataProvider
from sports_engine.providers.football_data import FootballDataProvider
from sports_engine.providers.local_csv import LocalCSVProvider
from sports_engine.providers.openfootball import OpenFootballProvider
from sports_engine.providers.statsbomb import StatsBombProvider

PROVIDER_CLASSES: dict[str, type[DataProvider]] = {
    "engsoccerdata": EngSoccerDataProvider,
    "openfootball": OpenFootballProvider,
    "statsbomb": StatsBombProvider,
    "football_data": FootballDataProvider,
    "local_csv": LocalCSVProvider,
}


def get_provider(name: str, settings=None) -> DataProvider:
    if name not in PROVIDER_CLASSES:
        raise KeyError(f"unknown provider {name!r}; known: {sorted(PROVIDER_CLASSES)}")
    return PROVIDER_CLASSES[name](settings)


def all_providers(settings=None) -> list[DataProvider]:
    return [cls(settings) for cls in PROVIDER_CLASSES.values()]
