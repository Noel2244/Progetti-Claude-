"""Experiment registry: immutable records, multiple-testing accounting, holdout log.

* every experiment row is immutable (SQLite triggers) and carries a content hash
  over all stored fields (``verify()`` recomputes it); corrections are new
  versions pointing to ``parent_id``;
* experiments are grouped in *families* (research questions); the number of
  candidate configurations per family drives a Bonferroni warning so that
  "one of hundreds looked good" is never mistaken for evidence;
* every access to the final holdout is appended to ``holdout_access``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sports_engine.core.hashing import canonical_json, short_id, stable_hash
from sports_engine.core.timeutils import iso, utcnow
from sports_engine.database.db import Database, dumps

HASHED_FIELDS = ("experiment_id", "version", "parent_id", "family", "name", "hypothesis", "created_at", "dataset_version",
                 "feature_version", "code_version", "model_version", "hyperparameters", "random_seed", "training_period",
                 "validation_period", "test_period", "used_holdout", "n_candidates", "metrics", "notes")


def code_version(root: Path | None = None) -> str:
    """Git commit (+'-dirty' when there are uncommitted changes); 'unknown' outside git."""
    try:
        cwd = str(root) if root else None
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=cwd, timeout=10, check=False)
        if head.returncode != 0:
            return "unknown"
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=cwd, timeout=10, check=False)
        return head.stdout.strip()[:12] + ("-dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _row_hash(row: dict) -> str:
    return stable_hash({k: row.get(k) for k in HASHED_FIELDS})


class ExperimentRegistry:
    def __init__(self, db: Database):
        self.db = db

    def record(self, *, family: str, name: str, hypothesis: str | None, metrics: dict,
               dataset_version: str | None, feature_version: str | None, code_version: str | None,
               model_version: str | None, hyperparameters: dict | None, random_seed: int | None,
               training_period: str | None, validation_period: str | None, test_period: str | None,
               used_holdout: bool = False, n_candidates: int = 1, notes: str | None = None,
               parent_id: str | None = None) -> str:
        created = iso(utcnow())
        version = 1
        if parent_id:
            prev = self.db.scalar("SELECT version FROM experiment WHERE experiment_id=?", (parent_id,))
            if prev is None:
                raise KeyError(f"unknown parent experiment {parent_id}")
            version = int(prev) + 1
        row = {
            "version": version, "parent_id": parent_id, "family": family, "name": name, "hypothesis": hypothesis,
            "created_at": created, "dataset_version": dataset_version, "feature_version": feature_version,
            "code_version": code_version, "model_version": model_version, "hyperparameters": dumps(hyperparameters or {}),
            "random_seed": random_seed, "training_period": training_period, "validation_period": validation_period,
            "test_period": test_period, "used_holdout": int(used_holdout), "n_candidates": int(n_candidates),
            "metrics": dumps(metrics), "notes": notes,
        }
        row["experiment_id"] = short_id("exp", family, name, created, stable_hash(row))
        row["content_hash"] = _row_hash(row)
        cols = list(HASHED_FIELDS) + ["content_hash"]
        self.db.execute(f"INSERT INTO experiment({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        tuple(row[c] for c in cols))
        return row["experiment_id"]

    def verify(self) -> list[str]:
        return [f"{r['experiment_id']}: content hash mismatch" for r in self.db.query("SELECT * FROM experiment")
                if _row_hash(r) != r["content_hash"]]

    def log_holdout_access(self, experiment_id: str | None, holdout_start: str, reason: str) -> int:
        if not reason or len(reason.strip()) < 10:
            raise ValueError("holdout access requires an explicit reason (>= 10 characters)")
        self.db.execute("INSERT INTO holdout_access(accessed_at, experiment_id, holdout_start, reason) VALUES (?,?,?,?)",
                        (iso(utcnow()), experiment_id, holdout_start, reason))
        return self.holdout_accesses(holdout_start)

    def holdout_accesses(self, holdout_start: str | None = None) -> int:
        if holdout_start:
            return int(self.db.scalar("SELECT COUNT(*) FROM holdout_access WHERE holdout_start=?", (holdout_start,)) or 0)
        return int(self.db.scalar("SELECT COUNT(*) FROM holdout_access") or 0)

    def family_stats(self, family: str, alpha: float = 0.05) -> dict:
        n_exp = int(self.db.scalar("SELECT COUNT(*) FROM experiment WHERE family=?", (family,)) or 0)
        n_cand = int(self.db.scalar("SELECT COALESCE(SUM(n_candidates),0) FROM experiment WHERE family=?", (family,)) or 0)
        tests = max(1, n_cand)
        return {
            "family": family, "experiments": n_exp, "candidate_configurations": n_cand,
            "bonferroni_alpha": alpha / tests,
            "warning": (f"{n_cand} configurations tested in this family: at alpha={alpha} about {alpha * tests:.1f} "
                        "false 'discoveries' are expected by chance. Demand confirmation on untouched data.")
            if tests > 1 else None,
        }

    def all_stats(self) -> dict:
        fams = [r["family"] for r in self.db.query("SELECT DISTINCT family FROM experiment")]
        return {"total_experiments": int(self.db.scalar("SELECT COUNT(*) FROM experiment") or 0),
                "holdout_accesses": self.holdout_accesses(),
                "families": [self.family_stats(f) for f in fams]}

    def list(self, limit: int = 50) -> list[dict]:
        return self.db.query(
            "SELECT experiment_id, version, family, name, created_at, code_version, used_holdout, n_candidates, test_period "
            "FROM experiment ORDER BY created_at DESC LIMIT ?", (limit,))


def dataset_fingerprint(db: Database, competitions: list[str] | None = None) -> str:
    where, params = "", ()
    if competitions:
        where = f"WHERE competition_id IN ({','.join('?' * len(competitions))})"
        params = tuple(competitions)
    rows = db.query(f"SELECT match_id, data_version FROM match {where} ORDER BY match_id", params)
    return stable_hash(canonical_json([(r["match_id"], r["data_version"]) for r in rows]), 16)
