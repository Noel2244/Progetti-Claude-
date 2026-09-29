from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from sports_engine.database.db import Database
from sports_engine.experiments.registry import ExperimentRegistry
from sports_engine.paper.engine import PaperEngine
from sports_engine.research_lab.simulate import simulate_league

MATCH_COLS = ["match_id", "competition_id", "season", "season_start_year", "match_date", "kickoff_utc", "kickoff_time_known",
              "timestamp_quality", "home_team_id", "away_team_id", "home_goals", "away_goals", "ht_home_goals",
              "ht_away_goals", "status", "result_available_at", "score_disputed", "stats_json"]


def load_synthetic(db: Database, m: pd.DataFrame, o: pd.DataFrame) -> None:
    now = "2020-01-01T00:00:00Z"
    rows = []
    for r in m.to_dict("records"):
        rows.append(tuple(r[c] for c in MATCH_COLS) + ("synthetic", '["synthetic"]', 1, 0, "v", "1", now, now))
    db.executemany(
        f"""INSERT INTO match({','.join(MATCH_COLS)}, primary_source, sources, n_sources, has_conflict, data_version,
            schema_version, created_at, updated_at) VALUES ({','.join('?' * (len(MATCH_COLS) + 8))})""", rows)
    db.executemany(
        """INSERT INTO odds_snapshot(match_id, source, bookmaker, market, selection, line, odds, snapshot_type, available_at,
           timestamp_quality, raw_sha256, ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(r["match_id"], "synthetic", r["bookmaker"], r["market"], r["selection"], None, r["odds"], r["snapshot_type"],
          r["available_at"], "EXACT", None, now) for r in o.to_dict("records")])
    db.execute("INSERT OR IGNORE INTO bookmaker(bookmaker_id, is_aggregate, created_at) SELECT DISTINCT bookmaker, 0, ? FROM odds_snapshot", (now,))


@pytest.fixture()
def paper_env(settings, db):
    m, o, _ = simulate_league(n_teams=10, seasons=3, start_year=2019, seed=9, market="efficient")
    # results strictly after 'now' must not be known yet: the store enforces it through result_available_at
    load_synthetic(db, m, o)
    return settings.with_overrides({"paper": {"horizon_days": 10, "primary_model": "dixon_coles"}}), db, m


def test_paper_run_versioning_and_immutability(paper_env):
    settings, db, m = paper_env
    eng = PaperEngine(settings, db)
    now = datetime(2021, 11, 3, 12, 0, tzinfo=timezone.utc)
    s1 = eng.run(now=now)
    assert s1["upcoming"] > 0 and s1["written"] > 0
    assert eng.verify_chain() == []
    # same information -> nothing new written
    s2 = eng.run(now=now)
    assert s2["written"] == 0 and s2["skipped_unchanged"] == s1["written"]
    # immutability enforced by the database itself
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE paper_prediction SET model_prob = 0.99")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM paper_prediction")
    # new information (later snapshot) -> new versions that point at the old ones
    later = datetime(2021, 11, 4, 12, 0, tzinfo=timezone.utc)
    s3 = eng.run(now=later)
    sup = db.scalar("SELECT COUNT(*) FROM paper_prediction WHERE supersedes IS NOT NULL")
    assert s3["written"] == 0 or sup > 0
    # every prediction has explicit cutoffs before kickoff and a reason list
    df = db.df("SELECT * FROM paper_prediction")
    ko = pd.to_datetime(df["kickoff_utc"], utc=True)
    assert (pd.to_datetime(df["prediction_timestamp"], utc=True) < ko).all()
    assert df["reasons"].notna().all()


def test_paper_reconcile_and_status(paper_env):
    settings, db, m = paper_env
    eng = PaperEngine(settings, db)
    eng.run(now=datetime(2021, 11, 3, 12, 0, tzinfo=timezone.utc))
    r = eng.reconcile(now=datetime(2021, 12, 31, tzinfo=timezone.utc))
    assert r["reconciled"] > 0
    st = eng.status()
    assert st["resolved"] > 0 and st["chain_ok"]
    assert 0 < st["mean_brier_binary"] < 1
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE paper_outcome SET pnl_units = 1000")


def test_tampering_detected(paper_env):
    settings, db, _ = paper_env
    eng = PaperEngine(settings, db)
    eng.run(now=datetime(2021, 11, 3, 12, 0, tzinfo=timezone.utc))
    db.execute("DROP TRIGGER paper_prediction_no_update")          # simulate an attacker bypassing SQLite
    db.execute("UPDATE paper_prediction SET model_prob = 0.99 WHERE seq = 1")
    assert eng.verify_chain()


def test_experiment_registry_immutable_and_verifiable(db):
    reg = ExperimentRegistry(db)
    e1 = reg.record(family="fam", name="a", hypothesis="h", metrics={"ll": 1.0}, dataset_version="d", feature_version="f",
                    code_version="c", model_version="m", hyperparameters={"k": 1}, random_seed=1, training_period="t",
                    validation_period="v", test_period="x", n_candidates=12)
    e2 = reg.record(family="fam", name="a-fix", hypothesis="h", metrics={"ll": 0.9}, dataset_version="d", feature_version="f",
                    code_version="c", model_version="m", hyperparameters={"k": 2}, random_seed=1, training_period="t",
                    validation_period="v", test_period="x", parent_id=e1)
    assert db.scalar("SELECT version FROM experiment WHERE experiment_id=?", (e2,)) == 2
    assert reg.verify() == []
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE experiment SET metrics='{}'")
    stats = reg.family_stats("fam")
    assert stats["candidate_configurations"] == 13 and stats["warning"]
    with pytest.raises(ValueError):
        reg.log_holdout_access(e1, "2025-07-01", "x")
    assert reg.log_holdout_access(e1, "2025-07-01", "final confirmation of champion") == 1
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM holdout_access")


def test_paper_over_under_has_real_interval(paper_env):
    settings, db, _ = paper_env
    PaperEngine(settings, db).run(now=datetime(2021, 11, 3, 12, 0, tzinfo=timezone.utc))
    ou = db.df("SELECT prob_low, prob_high, model_prob FROM paper_prediction WHERE market='OU'")
    assert len(ou) and ou["prob_low"].notna().all()
    assert (ou["prob_high"] - ou["prob_low"] > 0).all()
