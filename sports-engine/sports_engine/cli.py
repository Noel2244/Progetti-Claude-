"""Command-line interface:  python -m sports_engine <command> [...]

Run ``python -m sports_engine --help`` for the list of commands.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from sports_engine.core.config import load_settings
from sports_engine.core.logging import configure_logging
from sports_engine.core.timeutils import iso, parse_iso, utcnow

LEAKAGE_TESTS = ["tests/test_temporal_leakage.py", "tests/test_feature_leakage.py", "tests/test_point_in_time.py",
                 "tests/test_future_information.py"]


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, default=str, ensure_ascii=False))


def _ctx(args):
    s = load_settings(args.config)
    configure_logging(args.log_level, json_format=not args.plain_logs,
                      logfile=str(s.reports_dir / "logs" / "engine.log"))
    from sports_engine.database.db import Database
    return s, Database(s.database_path)


def _years(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    if "-" in spec:
        a, b = spec.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in spec.split(",")]


# ------------------------------------------------------------------ commands
def cmd_audit_env(args):
    from sports_engine.core.audit import environment_audit
    s = load_settings(args.config)
    _print(environment_audit(s.root))


def cmd_sources(args):
    s = load_settings(args.config)
    from sports_engine.providers.registry import all_providers
    rows = []
    for p in all_providers(s):
        i = p.info
        rows.append({"provider": i.name, "enabled": p.is_enabled(), "why_not": p.enabled_reason(), "license": i.license_id,
                     "tier": i.source_tier.name, "capabilities": list(i.capabilities),
                     "classes": [c.value for c in i.data_classes], "restrictions": list(i.restrictions),
                     "terms": i.terms_url})
    _print(rows)


def cmd_download(args):
    s, db = _ctx(args)
    from sports_engine.pipeline.acquisition import HistoricalDataAcquisitionPipeline
    providers = args.providers.split(",") if args.providers else ["engsoccerdata", "openfootball", "statsbomb", "football_data"]
    comps = args.competitions.split(",") if args.competitions else s.get("competitions")
    reps = HistoricalDataAcquisitionPipeline(s).run(providers, comps, _years(args.seasons), force=args.force)
    for r in reps:
        db.log_provider_status(r.provider, r.status, r.reason or "")
    _print([{**asdict(r), "downloaded": len(r.downloaded), "cached": len(r.cached), "unchanged": len(r.unchanged)} for r in reps])


def cmd_import_inbox(args):
    s, _ = _ctx(args)
    from sports_engine.pipeline.acquisition import HistoricalDataAcquisitionPipeline
    _print(HistoricalDataAcquisitionPipeline(s).import_inbox())


def cmd_ingest(args):
    s, db = _ctx(args)
    from sports_engine.pipeline.ingest import Ingestor
    rep = Ingestor(s, db).run_all(force=args.force)
    d = asdict(rep)
    d["datasets_ingested"] = len(d["datasets_ingested"])
    _print(d)


def cmd_validate(args):
    s, db = _ctx(args)
    from sports_engine.data.lake import RawDataLake
    from sports_engine.quality.pit_audit import pit_audit
    _print({"lake_integrity_problems": RawDataLake(s.data_dir).verify(),
            "issues": db.query("SELECT provider, severity, code, COUNT(*) n FROM ingestion_issue GROUP BY 1,2,3 ORDER BY n DESC"),
            "entity_review_open": db.query("SELECT source, country, raw_name, candidates, reason FROM entity_review WHERE status='OPEN'"),
            "conflicts": db.query("SELECT field, resolution_reason, COUNT(*) n FROM data_conflict GROUP BY 1,2"),
            "pit_audit": pit_audit(db)})


def cmd_coverage(args):
    s, db = _ctx(args)
    from sports_engine.quality.coverage import coverage_matrix, historical_data_report, persist_quality
    cov = coverage_matrix(db)
    out = s.reports_dir / "coverage"
    out.mkdir(parents=True, exist_ok=True)
    cov.to_csv(out / "coverage_matrix.csv", index=False)
    rep = historical_data_report(db, cov)
    q = persist_quality(db, cov) if len(cov) else []
    (out / "historical_data_report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    (out / "data_quality.json").write_text(json.dumps(q, indent=1, default=str), encoding="utf-8")
    (out / "coverage_matrix.md").write_text(cov.to_markdown(index=False) if hasattr(cov, "to_markdown") and _has_tabulate() else cov.to_string(index=False), encoding="utf-8")
    _print({k: v for k, v in rep.items() if k != "gaps"} | {"files": str(out)})


def _has_tabulate() -> bool:
    try:
        import tabulate  # noqa: F401
        return True
    except ImportError:
        return False


def cmd_pit_audit(args):
    s, db = _ctx(args)
    from sports_engine.quality.pit_audit import pit_audit
    rep = pit_audit(db)
    out = s.reports_dir / "pit_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    _print({k: rep[k] for k in ("passed", "checks", "match_timestamp_quality")})
    if not rep["passed"]:
        sys.exit(2)


def cmd_backtest(args):
    s, db = _ctx(args)
    from sports_engine.backtesting.runner import run_backtest
    out = run_backtest(s, db, competitions=args.competitions.split(","), test_start=date.fromisoformat(args.start),
                       test_end=date.fromisoformat(args.end), models=args.models.split(",") if args.models else None,
                       primary=args.primary, burn_in_years=args.burn_in, use_holdout=args.use_holdout,
                       holdout_reason=args.holdout_reason, family=args.family, name=args.name, bootstrap=args.bootstrap)
    r = out["result"]
    _print({"run_id": out["run_id"], "experiment_id": out["experiment_id"], "report": out["report"],
            "calibrators_saved": out["calibrators"], "runtime_s": r.runtime_seconds, "notes": r.notes,
            "metrics": {k: {kk: round(v[kk], 4) for kk in ("log_loss", "brier", "rps", "ece_mean")} | {"n": v["n"]}
                        for k, v in r.metrics.items() if not k.startswith("_")},
            "betting": r.betting})


def cmd_nested(args):
    """Nested walk-forward selection of one hyper-parameter; every candidate is counted as an experiment."""
    s, db = _ctx(args)
    from sports_engine.backtesting.nested import nested_walk_forward
    from sports_engine.experiments.registry import ExperimentRegistry, code_version, dataset_fingerprint
    from sports_engine.models.registry import model_factories
    from sports_engine.pit.store import HistoricalStore
    name, values = args.param.split("=")
    grid = [{name: float(v), "uncertainty": False} for v in values.split(",")]
    a, b = (int(x) for x in args.outer.split("-"))
    holdout = date.fromisoformat(s.get("holdout.start_date"))
    outer = [y for y in range(a, b + 1) if date(y + 1, 6, 30) < holdout]    # never touch the final holdout
    cv = code_version(s.root)
    store = HistoricalStore.from_db(db, args.competitions.split(","), with_odds=False)
    section = args.model if args.model in ("elo", "dixon_coles") else "poisson"
    res = nested_walk_forward(store, args.competitions.split(","), args.model, grid,
                              lambda params: model_factories(s, {section: params}), outer, args.inner_seasons)
    summary = {"outer_logloss": res.outer_logloss, "per_season": res.per_season}
    eid = ExperimentRegistry(db).record(
        family=f"nested:{args.model}:{name}", name=f"nested {args.model} {name} {args.outer}",
        hypothesis=f"choosing {name} by nested walk-forward improves out-of-sample log loss", metrics=summary,
        dataset_version=dataset_fingerprint(db, args.competitions.split(",")), feature_version=None, code_version=cv,
        model_version=args.model, hyperparameters={"grid": grid}, random_seed=None,
        training_period="expanding, before each inner window", validation_period=f"{args.inner_seasons} seasons before each outer season",
        test_period=f"{outer[0]}..{outer[-1]}" if outer else None, n_candidates=res.n_candidates_evaluated)
    _print({"experiment_id": eid, **summary, "n_candidates_evaluated": res.n_candidates_evaluated})


def _load_result(report_dir: Path):
    rep = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    ps = pd.read_csv(report_dir / "per_season.csv") if (report_dir / "per_season.csv").exists() else pd.DataFrame()
    return SimpleNamespace(metrics=rep["metrics"], comparisons=rep["comparisons"], per_season=ps), rep["meta"]


def _leakage_suite(root: Path) -> bool:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", *LEAKAGE_TESTS], cwd=root, capture_output=True, text=True,
                          timeout=3600, check=False)
    print(proc.stdout[-2000:], file=sys.stderr)
    return proc.returncode == 0


def cmd_gates(args):
    s, db = _ctx(args)
    from sports_engine.models.champion import ModelRegistry, evaluate_gates
    row = db.query("SELECT report_dir FROM backtest_run WHERE run_id=?", (args.run_id,))
    if not row:
        sys.exit(f"unknown run id {args.run_id}")
    result, meta = _load_result(Path(row[0]["report_dir"]))
    leak_ok = _leakage_suite(s.root) if not args.skip_leakage_suite else None
    report = evaluate_gates(result, args.model, args.reference, meta, leak_ok)
    _print(report)
    if args.promote:
        reg = ModelRegistry(db)
        key = reg.register(args.model, meta.get("code_version", "unknown"), {"run_id": args.run_id}, report)
        reg.promote(key, report, scope=args.scope)
        print(f"promoted {key} ({args.scope})", file=sys.stderr)


def cmd_paper(args):
    s, db = _ctx(args)
    from sports_engine.paper.engine import PaperEngine
    eng = PaperEngine(s, db)
    now = parse_iso(args.now) if args.now else None
    if args.action == "run":
        _print(eng.run(now=now, horizon_days=args.horizon))
    elif args.action == "reconcile":
        _print(eng.reconcile(now=now))
    elif args.action == "status":
        _print(eng.status())
    elif args.action == "verify":
        problems = eng.verify_chain()
        _print({"chain_ok": not problems, "problems": problems})
        if problems:
            sys.exit(2)


def cmd_daily(args):
    """Daily pipeline: acquire -> ingest -> quality -> reconcile -> predict -> report (each step isolated)."""
    s, db = _ctx(args)
    from sports_engine.paper.engine import PaperEngine
    from sports_engine.pipeline.acquisition import HistoricalDataAcquisitionPipeline
    from sports_engine.pipeline.ingest import Ingestor
    from sports_engine.pipeline.runner import PipelineRunner
    from sports_engine.quality.coverage import coverage_matrix, persist_quality
    from sports_engine.quality.pit_audit import pit_audit
    from sports_engine.reporting.daily import daily_report
    run = PipelineRunner(db)
    comps = s.get("competitions")
    acq = HistoricalDataAcquisitionPipeline(s)

    def download():
        reps = acq.run(["engsoccerdata", "openfootball", "statsbomb", "football_data"], comps)
        for r in reps:
            db.log_provider_status(r.provider, r.status, r.reason or "")
        return {"providers": {r.provider: r.status for r in reps},
                "degraded": any(r.status in ("DEGRADED", "UNAVAILABLE") for r in reps)}

    run.run("download", download, retries=1)
    run.run("import_inbox", acq.import_inbox)
    run.run("ingest", lambda: asdict(Ingestor(s, db).run_all()) | {"datasets_ingested": None}, retries=0, critical=True)
    run.run("quality", lambda: {"seasons": len(persist_quality(db, coverage_matrix(db)))}, requires=["ingest"])
    run.run("pit_audit", lambda: {"passed": pit_audit(db)["passed"]}, requires=["ingest"])
    eng = PaperEngine(s, db)
    run.run("paper_reconcile", eng.reconcile, requires=["ingest"])
    from sports_engine.quality.drift import run_drift_checks
    run.run("drift", lambda: {"alerts": [r for r in run_drift_checks(db, comps) if r["status"] == "ALERT"]},
            requires=["ingest"])
    paper = run.run("paper_predict", lambda: eng.run(horizon_days=args.horizon), requires=["ingest"])
    run.run("report", lambda: daily_report(db, s.reports_dir / "daily", paper.output if isinstance(paper.output, dict) else None))
    _print(run.summary())


def cmd_drift(args):
    s, db = _ctx(args)
    from sports_engine.quality.drift import run_drift_checks
    rows = run_drift_checks(db, s.get("competitions"))
    _print(rows)


def cmd_report(args):
    s, db = _ctx(args)
    from sports_engine.reporting.daily import daily_report, data_health, model_health
    if args.kind == "daily":
        _print(daily_report(db, s.reports_dir / "daily"))
    elif args.kind == "data-health":
        _print(data_health(db))
    elif args.kind == "model-health":
        _print(model_health(db))


def cmd_experiments(args):
    s, db = _ctx(args)
    from sports_engine.experiments.registry import ExperimentRegistry
    reg = ExperimentRegistry(db)
    _print({"stats": reg.all_stats(), "recent": reg.list(args.limit), "integrity_problems": reg.verify()})


def cmd_models(args):
    s, db = _ctx(args)
    from sports_engine.models.champion import ModelRegistry
    _print(ModelRegistry(db).list())


def cmd_journal(args):
    s, db = _ctx(args)
    db.execute("""INSERT INTO journal_entry(created_at, prediction_id, match_id, kind, selection_reason, rejection_reason,
                  my_expectation, what_happened, randomness, model_error, what_to_change, stake, odds, result, note)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (iso(utcnow()), args.prediction_id, args.match_id, args.kind, args.selection_reason, args.rejection_reason,
                args.my_expectation, args.what_happened, args.randomness, args.model_error, args.what_to_change,
                args.stake, args.odds, args.result, args.note))
    _print({"ok": True})


def cmd_simulate(args):
    """Research-lab sanity check on SYNTHETIC data where the truth is known."""
    configure_logging(args.log_level, json_format=not args.plain_logs)
    from sports_engine.backtesting.walkforward import BacktestConfig, WalkForwardBacktest
    from sports_engine.models.registry import model_factories
    from sports_engine.pit.store import HistoricalStore
    from sports_engine.reporting.backtest_report import interpret
    from sports_engine.research_lab.simulate import simulate_league
    bias = 0.06 if args.scenario == "biased" else 0.0
    m, o, _ = simulate_league(seasons=args.seasons, market="efficient", home_fav_bias=bias, seed=args.seed)
    store = HistoricalStore(m, o)
    first = int(m["season_start_year"].min())
    cfg = BacktestConfig(competitions=["ITA1"], test_start=date(first + 2, 7, 1), test_end=date(first + args.seasons, 7, 1),
                         burn_in_start=date(first, 7, 1), calibration_min_train=300, bootstrap=500)
    res = WalkForwardBacktest(store, cfg, model_factories()).run()
    _print({"scenario": args.scenario, "SYNTHETIC": True, "interpretation": interpret(res), "betting": res.betting})


def cmd_serve(args):
    s = load_settings(args.config)
    import uvicorn
    from sports_engine.api.app import create_app
    if args.host not in ("127.0.0.1", "localhost") and not s.secret("SPORTS_ENGINE_API_TOKEN"):
        sys.exit("refusing to listen on a non-local interface without SPORTS_ENGINE_API_TOKEN set")
    uvicorn.run(create_app(s), host=args.host, port=args.port, log_level="warning")


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sports_engine", description="Personal sports research engine (paper mode only)")
    p.add_argument("--config", default=None)
    p.add_argument("--log-level", default="WARNING")
    p.add_argument("--plain-logs", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("audit-env", help="environment audit").set_defaults(fn=cmd_audit_env)
    sub.add_parser("sources", help="list providers, licenses and status").set_defaults(fn=cmd_sources)
    d = sub.add_parser("download-history", help="acquire historical data into the immutable lake")
    d.add_argument("--providers"); d.add_argument("--competitions"); d.add_argument("--seasons", help="e.g. 2000-2024")
    d.add_argument("--force", action="store_true")
    d.set_defaults(fn=cmd_download)
    sub.add_parser("import-inbox", help="import manual files from data/inbox").set_defaults(fn=cmd_import_inbox)
    i = sub.add_parser("ingest", help="parse, validate, resolve entities, build canonical matches")
    i.add_argument("--force", action="store_true")
    i.set_defaults(fn=cmd_ingest)
    sub.add_parser("validate-data", help="integrity, contract issues, conflicts, PIT audit").set_defaults(fn=cmd_validate)
    sub.add_parser("coverage", help="coverage matrix, gaps and historical data report").set_defaults(fn=cmd_coverage)
    sub.add_parser("pit-audit", help="point-in-time audit (exit 2 on failure)").set_defaults(fn=cmd_pit_audit)

    b = sub.add_parser("backtest", help="walk-forward backtest")
    b.add_argument("--competitions", default="ITA1"); b.add_argument("--start", required=True); b.add_argument("--end", required=True)
    b.add_argument("--models"); b.add_argument("--primary", default="dixon_coles"); b.add_argument("--burn-in", type=int, default=3)
    b.add_argument("--use-holdout", action="store_true"); b.add_argument("--holdout-reason")
    b.add_argument("--family", default="baseline_models"); b.add_argument("--name"); b.add_argument("--bootstrap", type=int, default=1000)
    b.set_defaults(fn=cmd_backtest)

    ns = sub.add_parser("nested", help="nested walk-forward hyper-parameter selection")
    ns.add_argument("--competitions", default="ITA1"); ns.add_argument("--model", default="dixon_coles")
    ns.add_argument("--param", required=True, help="e.g. xi_per_day=0,0.001,0.0019,0.003")
    ns.add_argument("--outer", required=True, help="outer test seasons, e.g. 2015-2024"); ns.add_argument("--inner-seasons", type=int, default=2)
    ns.set_defaults(fn=cmd_nested)

    g = sub.add_parser("gates", help="evaluate promotion gates for a backtest run (runs the leakage suite)")
    g.add_argument("--run-id", required=True); g.add_argument("--model", default="dixon_coles"); g.add_argument("--reference", default="elo")
    g.add_argument("--promote", action="store_true"); g.add_argument("--scope", choices=["probability", "betting"], default="probability")
    g.add_argument("--skip-leakage-suite", action="store_true", help="(gate no_leakage will then FAIL)")
    g.set_defaults(fn=cmd_gates)

    pp = sub.add_parser("paper", help="live paper predictions")
    pp.add_argument("action", choices=["run", "reconcile", "status", "verify"])
    pp.add_argument("--now", help="ISO timestamp (default: now)"); pp.add_argument("--horizon", type=int)
    pp.set_defaults(fn=cmd_paper)

    dl = sub.add_parser("daily", help="daily pipeline")
    dl.add_argument("--horizon", type=int, default=None)
    dl.set_defaults(fn=cmd_daily)
    sub.add_parser("drift", help="league / performance / calibration drift checks").set_defaults(fn=cmd_drift)
    r = sub.add_parser("report", help="reports")
    r.add_argument("kind", choices=["daily", "data-health", "model-health"])
    r.set_defaults(fn=cmd_report)
    e = sub.add_parser("experiments", help="experiment registry")
    e.add_argument("--limit", type=int, default=20)
    e.set_defaults(fn=cmd_experiments)
    sub.add_parser("models", help="champion/challenger registry").set_defaults(fn=cmd_models)

    j = sub.add_parser("journal", help="add a personal research journal entry")
    j.add_argument("--kind", default="note", choices=["note", "manual_bet", "review"])
    for f in ("prediction-id", "match-id", "selection-reason", "rejection-reason", "my-expectation", "what-happened",
              "randomness", "model-error", "what-to-change", "result", "note"):
        j.add_argument(f"--{f}")
    j.add_argument("--stake", type=float); j.add_argument("--odds", type=float)
    j.set_defaults(fn=cmd_journal)

    sm = sub.add_parser("simulate", help="synthetic sanity check (efficient vs biased market)")
    sm.add_argument("--scenario", choices=["efficient", "biased"], default="efficient")
    sm.add_argument("--seasons", type=int, default=6); sm.add_argument("--seed", type=int, default=1)
    sm.set_defaults(fn=cmd_simulate)

    sv = sub.add_parser("serve", help="local API + dashboard")
    sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
