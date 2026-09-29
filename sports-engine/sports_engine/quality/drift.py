"""Drift detection (directive section 75).

Three families, each returning OK / WARN / ALERT / INSUFFICIENT_SAMPLE and a suggested
action (NONE / REVIEW / RETRAIN / DOWNWEIGHT / RETIRE):

* league-behaviour drift - home-win rate, draw rate (two-proportion z-tests) and goals per
  match (Welch t) in a recent window vs a reference window, all from *visible* results;
* model performance drift - mean log loss of resolved live paper predictions vs the
  backtest's expectation for the same model (one-sample t on per-prediction losses);
* calibration drift - calibration-in-the-large of resolved paper predictions
  (observed frequency vs mean predicted probability, z-test).

Small samples never raise alarms: below ``min_n`` the status is INSUFFICIENT_SAMPLE.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy import stats

from sports_engine.core.timeutils import iso, utcnow
from sports_engine.database.db import Database, dumps


@dataclass
class DriftResult:
    scope: str
    metric: str
    reference: float | None
    current: float | None
    statistic: float | None
    p_value: float | None
    n_reference: int
    n_current: int
    status: str
    action: str
    detail: str = ""


def _status(p: float | None, n_cur: int, min_n: int, warn: float = 0.01, alert: float = 0.001) -> tuple[str, str]:
    if p is None or n_cur < min_n:
        return "INSUFFICIENT_SAMPLE", "NONE"
    if p < alert:
        return "ALERT", "RETRAIN"
    if p < warn:
        return "WARN", "REVIEW"
    return "OK", "NONE"


def _two_prop(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    p = (k1 + k2) / (n1 + n2)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (k2 / n2 - k1 / n1) / se
    return float(z), float(2 * stats.norm.sf(abs(z)))


def league_drift(results: pd.DataFrame, scope: str, recent: int = 380, reference: int = 1900, min_n: int = 150) -> list[DriftResult]:
    """Compare the last ``recent`` matches with the ``reference`` matches before them."""
    r = results.sort_values("result_available_at")
    cur, ref = r.tail(recent), r.iloc[max(0, len(r) - recent - reference): max(0, len(r) - recent)]
    out = []
    if len(ref) < min_n or len(cur) < 1:
        return [DriftResult(scope, m, None, None, None, None, len(ref), len(cur), "INSUFFICIENT_SAMPLE", "NONE", "not enough history")
                for m in ("home_win_rate", "draw_rate", "goals_per_match")]
    for name, f in (("home_win_rate", lambda d: d["home_goals"] > d["away_goals"]),
                    ("draw_rate", lambda d: d["home_goals"] == d["away_goals"])):
        k1, k2 = int(f(ref).sum()), int(f(cur).sum())
        z, p = _two_prop(k1, len(ref), k2, len(cur))
        st, act = _status(p, len(cur), min_n)
        out.append(DriftResult(scope, name, k1 / len(ref), k2 / len(cur), z, p, len(ref), len(cur), st, act))
    g1, g2 = (ref["home_goals"] + ref["away_goals"]).to_numpy(float), (cur["home_goals"] + cur["away_goals"]).to_numpy(float)
    t, p = stats.ttest_ind(g2, g1, equal_var=False)
    st, act = _status(float(p), len(cur), min_n)
    out.append(DriftResult(scope, "goals_per_match", float(g1.mean()), float(g2.mean()), float(t), float(p), len(g1), len(g2), st, act))
    return out


def performance_drift(losses: np.ndarray, expected_mean: float, scope: str, min_n: int = 200) -> DriftResult:
    """One-sided test: is live log loss worse than the backtest expectation?"""
    n = len(losses)
    if n < 2:
        return DriftResult(scope, "log_loss", expected_mean, float(losses.mean()) if n else None, None, None, 0, n,
                           "INSUFFICIENT_SAMPLE", "NONE", "no resolved predictions")
    t, p_two = stats.ttest_1samp(losses, expected_mean)
    p = float(p_two / 2) if t > 0 else 1.0 - float(p_two / 2)
    st, act = _status(p, n, min_n)
    if st == "ALERT":
        act = "DOWNWEIGHT"
    return DriftResult(scope, "log_loss", expected_mean, float(losses.mean()), float(t), p, 0, n, st, act)


def calibration_drift(prob: np.ndarray, outcome: np.ndarray, scope: str, min_n: int = 200) -> DriftResult:
    n = len(prob)
    if n < 2:
        return DriftResult(scope, "calibration_in_the_large", None, None, None, None, 0, n, "INSUFFICIENT_SAMPLE", "NONE")
    exp, obs = float(prob.mean()), float(outcome.mean())
    se = float(np.sqrt(np.sum(prob * (1 - prob)))) / n
    z = (obs - exp) / se if se > 0 else 0.0
    p = float(2 * stats.norm.sf(abs(z)))
    st, act = _status(p, n, min_n)
    return DriftResult(scope, "calibration_in_the_large", exp, obs, z, p, 0, n, st, act)


def run_drift_checks(db: Database, competitions: list[str], expected_logloss: dict[str, float] | None = None) -> list[dict]:
    from sports_engine.pit.store import HistoricalStore
    store = HistoricalStore.from_db(db, competitions, with_odds=False)
    snap = store.as_of(utcnow())
    out: list[DriftResult] = []
    for cid in competitions:
        out += league_drift(snap.results([cid], exclude_disputed=True), f"league:{cid}")
    # latest pre-kickoff version per match/selection only (earlier versions were superseded)
    res = db.df("""SELECT p.model_name, p.selection, p.model_prob, o.outcome, o.log_loss
                   FROM paper_prediction p
                   JOIN (SELECT match_id, market, selection, MAX(seq) seq FROM paper_prediction GROUP BY 1,2,3) l ON l.seq = p.seq
                   JOIN paper_outcome o ON o.prediction_id = p.prediction_id
                   WHERE p.market = '1X2'""")
    if expected_logloss is None:
        expected_logloss = latest_backtest_logloss(db)
    if len(res):
        res["hit"] = res["outcome"].isin(["WIN", "NOT_BET_HIT"]).astype(float)
        for (model, sel), g in res.groupby(["model_name", "selection"]):
            # per selection: over all three outcomes the check would be vacuous (both sides sum to 1)
            out.append(calibration_drift(g["model_prob"].to_numpy(float), g["hit"].to_numpy(), f"paper:{model}:{sel}"))
        for model, g in res.groupby("model_name"):
            if model in expected_logloss:
                # -log p(outcome that happened) == multiclass log loss of that match, comparable to backtests
                losses = g[g["hit"] == 1]["log_loss"].to_numpy(float)
                out.append(performance_drift(losses, expected_logloss[model], f"paper:{model}"))
    now = iso(utcnow())
    rows = [asdict(r) for r in out]
    db.executemany(
        "INSERT INTO drift_record(computed_at, scope, metric, reference, current, statistic, status, action, details) VALUES (?,?,?,?,?,?,?,?,?)",
        [(now, r["scope"], r["metric"], r["reference"], r["current"], r["statistic"], r["status"], r["action"],
          dumps({"p_value": r["p_value"], "n_reference": r["n_reference"], "n_current": r["n_current"], "detail": r["detail"]}))
         for r in rows])
    return rows


def latest_backtest_logloss(db: Database) -> dict[str, float]:
    """Expected out-of-sample log loss per model from the most recent backtest run."""
    import json
    row = db.query("SELECT summary FROM backtest_run ORDER BY created_at DESC LIMIT 1")
    if not row:
        return {}
    summ = json.loads(row[0]["summary"] or "{}")
    out = {}
    for k, v in summ.items():
        if k.endswith(":calibrated") and isinstance(v, dict) and "log_loss" in v:
            out[k.split(":")[0]] = float(v["log_loss"])
    return out
