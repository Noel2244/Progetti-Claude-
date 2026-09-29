"""Backtest service: DB -> point-in-time store -> walk-forward -> registry -> reports."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from sports_engine.backtesting.walkforward import BacktestConfig, BacktestResult, WalkForwardBacktest
from sports_engine.calibration.calibrators import calibrator_to_dict, select_calibrator
from sports_engine.core.config import Settings
from sports_engine.core.errors import HoldoutAccessError
from sports_engine.core.hashing import short_id, stable_hash
from sports_engine.core.logging import get_logger, log_event
from sports_engine.core.timeutils import iso, utcnow
from sports_engine.database.db import Database, dumps
from sports_engine.decision.engine import DecisionConfig
from sports_engine.decision.staking import RiskLimits, StakingConfig
from sports_engine.experiments.registry import ExperimentRegistry, code_version, dataset_fingerprint
from sports_engine.models.registry import model_factories
from sports_engine.pit.store import HistoricalStore
from sports_engine.reporting.backtest_report import write_backtest_report

log = get_logger("backtest.runner")
FEATURE_VERSION = "goals-elo-v1"


def run_backtest(settings: Settings, db: Database, *, competitions: list[str], test_start: date, test_end: date,
                 models: list[str] | None = None, primary: str = "dixon_coles", burn_in_years: int = 3,
                 use_holdout: bool = False, holdout_reason: str | None = None, family: str = "baseline_models",
                 name: str | None = None, overrides: dict | None = None, bootstrap: int = 1000,
                 save_calibrators: bool = True, hypothesis: str | None = None) -> dict:
    holdout = settings.get("holdout.start_date")
    holdout_start = date.fromisoformat(holdout) if holdout else None
    registry = ExperimentRegistry(db)
    if use_holdout:
        if not holdout_reason:
            raise HoldoutAccessError("using the final holdout requires --holdout-reason")
    store = HistoricalStore.from_db(db, competitions)
    models = models or ["climatology", "elo", "poisson", "poisson_weighted", "dixon_coles", "market"]
    cfg = BacktestConfig(
        competitions=competitions, test_start=test_start, test_end=test_end, models=models, primary_model=primary,
        burn_in_start=date(test_start.year - burn_in_years, test_start.month, 1),
        holdout_start=holdout_start, use_holdout=use_holdout,
        margin_method=settings.get("decision.margin_method", "power"),
        calibration_candidates=tuple(settings.get("calibration.candidates", ["identity", "temperature", "dirichlet", "ovr_isotonic"])),
        calibration_min_train=int(settings.get("calibration.min_train_predictions", 600)),
        calibration_min_improvement=float(settings.get("calibration.min_improvement_logloss", 0.002)),
        decision=DecisionConfig.from_settings(settings), staking=StakingConfig.from_settings(settings),
        risk=RiskLimits.from_settings(settings), bootstrap=bootstrap,
    )
    result = WalkForwardBacktest(store, cfg, model_factories(settings, overrides)).run()
    fp = dataset_fingerprint(db, competitions)
    cv = code_version(settings.root)
    sources = sorted({s for js in db.df(
        f"SELECT sources FROM match WHERE competition_id IN ({','.join('?' * len(competitions))})", competitions)["sources"]
        for s in json.loads(js)})
    summary = {k: {kk: v[kk] for kk in ("n", "log_loss", "brier", "rps", "ece_mean") if kk in v}
               for k, v in result.metrics.items() if not k.startswith("_")}
    summary["betting"] = {k: v for k, v in result.betting.items() if k not in ("no_bet_reasons",)}
    exp_id = registry.record(
        family=family, name=name or f"walkforward:{','.join(competitions)}:{test_start}:{test_end}",
        hypothesis=hypothesis or "baseline probability models beat league base rates out-of-sample",
        metrics=summary, dataset_version=fp, feature_version=FEATURE_VERSION, code_version=cv,
        model_version=",".join(models), hyperparameters={"models": settings.get("models"), "overrides": overrides or {}},
        random_seed=cfg.seed, training_period=f"expanding window up to each decision time (burn-in from {cfg.burn_in_start})",
        validation_period="calibration selected on prior out-of-sample seasons",
        test_period=f"{test_start}..{min(test_end, (holdout_start or test_end))}", used_holdout=use_holdout,
        n_candidates=len(models), notes="; ".join(result.notes) or None,
    )
    if use_holdout:
        n = registry.log_holdout_access(exp_id, holdout, holdout_reason)
        if n > 1:
            result.notes.append(f"WARNING: the final holdout has now been accessed {n} times - it is contaminated; define a new holdout.")
    run_id = short_id("bt", exp_id)
    out_dir = settings.reports_dir / "backtests" / run_id
    meta = {"run_id": run_id, "experiment_id": exp_id, "dataset_fingerprint": fp, "code_version": cv,
            "created_at": iso(utcnow()), "sources": ", ".join(sources), "feature_version": FEATURE_VERSION,
            "multiple_testing": registry.family_stats(family)}
    paths = write_backtest_report(result, out_dir, meta)
    db.execute("INSERT INTO backtest_run(run_id, experiment_id, created_at, config, summary, report_dir) VALUES (?,?,?,?,?,?)",
               (run_id, exp_id, meta["created_at"], dumps(result.config), dumps(summary), str(out_dir)))
    cal_saved = save_live_calibrators(settings, result, fp, run_id) if save_calibrators else {}
    log_event(log, "backtest done", run_id=run_id, experiment=exp_id, runtime=result.runtime_seconds)
    return {"run_id": run_id, "experiment_id": exp_id, "report": paths, "result": result, "meta": meta,
            "calibrators": cal_saved}


def save_live_calibrators(settings: Settings, result: BacktestResult, dataset_fp: str, run_id: str) -> dict:
    """Select + fit, per model, a calibrator on ALL out-of-sample predictions of the run (for live use)."""
    out_dir = settings.path("paths.models_dir", "models") / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = {}
    preds = result.predictions
    for model, g in preds.groupby("model"):
        if model == "market":
            continue
        seasons = sorted(g["season_start_year"].unique())
        if len(seasons) < 3:
            continue
        val = seasons[-2:]
        tr, va = g[~g["season_start_year"].isin(val)], g[g["season_start_year"].isin(val)]
        P = lambda df: df[["p_H", "p_D", "p_A"]].to_numpy()
        choice = select_calibrator(P(tr), tr["y"].to_numpy(), P(va), va["y"].to_numpy(),
                                   tuple(settings.get("calibration.candidates", ["identity", "temperature", "dirichlet", "ovr_isotonic"])),
                                   float(settings.get("calibration.min_improvement_logloss", 0.002)),
                                   int(settings.get("calibration.min_train_predictions", 600)))
        cal = choice.calibrator if choice.method == "identity" else type(choice.calibrator)().fit(P(g), g["y"].to_numpy())
        doc = {"model": model, "run_id": run_id, "dataset_fingerprint": dataset_fp, "created_at": iso(utcnow()),
               "fitted_on": {"n": int(len(g)), "seasons": [int(s) for s in seasons],
                             "last_decision_time": str(pd.Timestamp(g["decision_time"].max()))},
               "selection": {"method": choice.method, "reason": choice.reason,
                             "validation_logloss": {k: float(v) for k, v in choice.validation.items()}},
               "calibrator": calibrator_to_dict(cal)}
        (out_dir / f"{model}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
        saved[model] = choice.method
    return saved
