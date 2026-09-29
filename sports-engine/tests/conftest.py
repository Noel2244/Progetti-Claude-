from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from sports_engine.core.config import load_settings
from sports_engine.database.db import Database
from sports_engine.pit.store import HistoricalStore
from sports_engine.research_lab.simulate import simulate_league

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def synthetic():
    """Two-season synthetic league with an efficient market (clearly SYNTHETIC)."""
    m, o, truth = simulate_league(n_teams=10, seasons=3, start_year=2019, seed=3, market="efficient")
    return m, o, truth


@pytest.fixture()
def store(synthetic):
    m, o, _ = synthetic
    return HistoricalStore(m, o)


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTS_ENGINE_DATA_DIR", str(tmp_path / "data"))
    s = load_settings(overrides={"paths": {"reports_dir": str(tmp_path / "reports"), "models_dir": str(tmp_path / "models")}})
    return s


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "test.sqlite")
    yield d
    d.close()


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")
