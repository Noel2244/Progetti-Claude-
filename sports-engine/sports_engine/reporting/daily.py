"""Daily / data-health / model-health reports (Markdown + JSON)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from sports_engine.core.timeutils import iso, utcnow
from sports_engine.database.db import Database
from sports_engine.experiments.registry import ExperimentRegistry
from sports_engine.models.champion import ModelRegistry
from sports_engine.reporting.backtest_report import markdown_to_html


def data_health(db: Database) -> dict:
    prov = db.df("""SELECT provider, status, message, MAX(checked_at) checked_at FROM provider_status GROUP BY provider""")
    return {
        "matches": db.scalar("SELECT COUNT(*) FROM match"),
        "newest_result": db.scalar("SELECT MAX(match_date) FROM match WHERE status='FINISHED'"),
        "overdue_results": db.scalar("SELECT COUNT(*) FROM match WHERE status='UNKNOWN'"),
        "open_entity_reviews": db.scalar("SELECT COUNT(*) FROM entity_review WHERE status='OPEN'"),
        "conflicts": db.scalar("SELECT COUNT(*) FROM data_conflict"),
        "ingestion_errors": db.scalar("SELECT COUNT(*) FROM ingestion_issue WHERE severity='ERROR'"),
        "providers": prov.to_dict("records"),
        "last_pipeline": db.query("SELECT run_id, task, status, finished_at FROM pipeline_run ORDER BY finished_at DESC LIMIT 12"),
    }


def model_health(db: Database) -> dict:
    return {"registry": ModelRegistry(db).list(), "experiments": ExperimentRegistry(db).all_stats(),
            "last_backtests": db.query("SELECT run_id, created_at, report_dir FROM backtest_run ORDER BY created_at DESC LIMIT 5"),
            "drift": db.query("SELECT * FROM drift_record ORDER BY computed_at DESC LIMIT 10")}


def daily_report(db: Database, out_dir: Path, paper_summary: dict | None = None) -> dict:
    now = iso(utcnow())
    latest = db.df("""SELECT p.* FROM paper_prediction p JOIN (SELECT match_id, market, selection, MAX(seq) seq
                      FROM paper_prediction GROUP BY 1,2,3) l ON l.seq=p.seq
                      WHERE p.kickoff_utc IS NULL OR p.kickoff_utc > ? ORDER BY p.kickoff_utc, p.match_id""", (now,))
    teams = {r["team_id"]: r["name"] for r in db.query("SELECT team_id, name FROM team")}
    matches = db.df("SELECT match_id, home_team_id, away_team_id, match_date FROM match")
    mm = matches.set_index("match_id") if len(matches) else matches
    L = [f"# Daily report - {now[:10]}\n",
         "> Paper mode. Research output, not betting advice. 'NO BET' is a valid and frequent outcome.\n"]
    L.append("## FACT - data health\n")
    dh = data_health(db)
    for k in ("matches", "newest_result", "overdue_results", "open_entity_reviews", "conflicts", "ingestion_errors"):
        L.append(f"- {k}: {dh[k]}")
    if paper_summary:
        L.append(f"- paper run: {json.dumps({k: v for k, v in paper_summary.items() if k != 'status_counts'}, default=str)}")
    L.append("\n## MODEL OUTPUT / MARKET DATA - upcoming (latest version per selection)\n")
    if latest.empty:
        L.append("- No upcoming paper predictions.")
    else:
        L.append("| kickoff (UTC) | match | market | sel | model p | [low, high] | market p | odds | EV | status | reasons |")
        L.append("|---|---|---|---|---:|---|---:|---:|---:|---|---|")
        for r in latest.itertuples(index=False):
            h = teams.get(mm.loc[r.match_id, "home_team_id"], "?") if r.match_id in mm.index else "?"
            a = teams.get(mm.loc[r.match_id, "away_team_id"], "?") if r.match_id in mm.index else "?"
            reasons = ", ".join(json.loads(r.reasons)) or "-"
            fmt = lambda x, f="{:.3f}": "-" if x is None or pd.isna(x) else f.format(x)
            L.append(f"| {r.kickoff_utc or '(date only)'} | {h} v {a} | {r.market}{'' if pd.isna(r.line) else r.line} | {r.selection} | "
                     f"{r.model_prob:.3f} | [{fmt(r.prob_low)}, {fmt(r.prob_high)}] | {fmt(r.market_prob)} | {fmt(r.odds, '{:.2f}')} | "
                     f"{fmt(r.ev, '{:+.3f}')} | {r.status} | {reasons} |")
        counts = latest["status"].value_counts().to_dict()
        L.append(f"\nStatus counts: {counts}")
    L.append("\n## INTERPRETATION\n")
    if latest.empty or not (latest["status"].isin(["CANDIDATE", "STRONG_CANDIDATE"])).any():
        L.append("- No candidate passes every check today. This is the expected state most days.")
    else:
        L.append("- Candidates listed above passed every automated check; they remain hypotheses with uncertainty, "
                 "evaluated only in paper mode.")
    if not latest.empty and latest["odds"].isna().all():
        L.append("- No market odds were available to the engine, so no value assessment is possible (INSUFFICIENT_DATA). "
                 "Provide timestamped odds (data/inbox/odds_*.csv) or enable an odds source you are entitled to use.")
    md = "\n".join(L)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"daily_{now[:10]}"
    (out_dir / f"{stem}.md").write_text(md, encoding="utf-8")
    (out_dir / f"{stem}.html").write_text(markdown_to_html(md, f"Daily {now[:10]}"), encoding="utf-8")
    (out_dir / f"{stem}.json").write_text(json.dumps({"generated_at": now, "data_health": dh, "paper": paper_summary,
                                                      "upcoming": latest.to_dict("records")}, indent=1, default=str), encoding="utf-8")
    if not latest.empty:
        latest.to_csv(out_dir / f"{stem}.csv", index=False)
    return {"markdown": str(out_dir / f"{stem}.md"), "rows": int(len(latest))}
