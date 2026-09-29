"""Local FastAPI service + dashboard.

Security posture: binds to 127.0.0.1 by default (the CLI refuses non-local hosts
without a token); every endpoint except POST /journal is read-only; POST
requires ``SPORTS_ENGINE_API_TOKEN`` when one is configured; inputs are typed
and bounded; file paths are never taken from requests.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from sports_engine.core.config import Settings, load_settings
from sports_engine.database.db import Database

STATIC = Path(__file__).with_name("static")
ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    s = settings or load_settings()
    app = FastAPI(title="Personal Sports Research Engine", version="0.1.0",
                  description="Paper mode only. Research output, not betting advice.")
    state = {"db": db}

    def get_db() -> Database:
        if state["db"] is None:
            state["db"] = Database(s.database_path)
        return state["db"]

    def check_id(value: str) -> str:
        if not ID_RE.match(value):
            raise HTTPException(400, "invalid id")
        return value

    def require_token(x_api_token: str | None = Header(default=None)) -> None:
        token = s.secret("SPORTS_ENGINE_API_TOKEN")
        if token and x_api_token != token:
            raise HTTPException(401, "missing or invalid X-API-Token")

    teams_cache: dict[str, str] = {}

    def team_name(dbx: Database, tid: str) -> str:
        if not teams_cache:
            teams_cache.update({r["team_id"]: r["name"] for r in dbx.query("SELECT team_id, name FROM team")})
        return teams_cache.get(tid, tid)

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    def health(dbx: Database = Depends(get_db)):
        from sports_engine.paper.engine import PaperEngine
        return {"status": "ok", "mode": "paper", "matches": dbx.scalar("SELECT COUNT(*) FROM match"),
                "paper_predictions": dbx.scalar("SELECT COUNT(*) FROM paper_prediction"),
                "paper_chain_ok": not PaperEngine(s, dbx).verify_chain(),
                "last_pipeline": dbx.query("SELECT task, status, finished_at FROM pipeline_run ORDER BY finished_at DESC LIMIT 8")}

    @app.get("/matches")
    def matches(competition: str = Query("ITA1", max_length=8), season: str | None = Query(None, max_length=9),
                status: str | None = Query(None, max_length=12), limit: int = Query(200, ge=1, le=2000),
                dbx: Database = Depends(get_db)):
        sql = "SELECT * FROM match WHERE competition_id=?"
        params: list = [competition]
        if season:
            sql += " AND season=?"; params.append(season)
        if status:
            sql += " AND status=?"; params.append(status)
        sql += " ORDER BY match_date DESC LIMIT ?"; params.append(limit)
        rows = dbx.query(sql, params)
        for r in rows:
            r["home"], r["away"] = team_name(dbx, r["home_team_id"]), team_name(dbx, r["away_team_id"])
        return rows

    @app.get("/matches/{match_id}")
    def match_detail(match_id: str, dbx: Database = Depends(get_db)):
        check_id(match_id)
        m = dbx.query("SELECT * FROM match WHERE match_id=?", (match_id,))
        if not m:
            raise HTTPException(404, "unknown match")
        m = m[0]
        m["home"], m["away"] = team_name(dbx, m["home_team_id"]), team_name(dbx, m["away_team_id"])
        preds = dbx.query("SELECT * FROM paper_prediction WHERE match_id=? ORDER BY seq", (match_id,))
        latest = preds[-1] if preds else None
        matrix = None
        if latest:
            pl = json.loads(latest["payload"])
            lh, la = (pl.get("expected_goals") or [None, None])
            if lh and la:
                from sports_engine.models.score_matrix import score_matrix
                full, _ = score_matrix(lh, la, pl.get("rho", 0.0))
                grid = np.zeros((4, 4))
                for i in range(full.shape[0]):
                    for j in range(full.shape[1]):
                        grid[min(i, 3), min(j, 3)] += full[i, j]
                matrix = {"labels": ["0", "1", "2", "3+"], "home_rows_away_cols": grid.round(4).tolist()}
        return {
            "match": m,
            "sources": dbx.query("SELECT source, home_team_raw, away_team_raw, home_goals, away_goals, kickoff_utc, timestamp_quality FROM source_match WHERE match_id=?", (match_id,)),
            "conflicts": dbx.query("SELECT field, source_a, value_a, source_b, value_b, resolution, resolution_reason FROM data_conflict WHERE entity_id=?", (match_id,)),
            "odds": dbx.query("SELECT bookmaker, market, selection, line, odds, snapshot_type, available_at, timestamp_quality FROM odds_snapshot WHERE match_id=? ORDER BY available_at", (match_id,)),
            "paper_predictions": [{**p, "payload": json.loads(p["payload"]), "reasons": json.loads(p["reasons"])} for p in preds],
            "score_matrix": matrix,
        }

    @app.get("/predictions")
    def predictions(limit: int = Query(200, ge=1, le=5000), dbx: Database = Depends(get_db)):
        rows = dbx.query("""SELECT p.*, o.outcome, o.pnl_units, o.clv_price FROM paper_prediction p
                            LEFT JOIN paper_outcome o ON o.prediction_id=p.prediction_id ORDER BY p.seq DESC LIMIT ?""", (limit,))
        for r in rows:
            r["reasons"] = json.loads(r["reasons"])
            r.pop("payload", None)
        return rows

    @app.get("/value")
    def value(include_no_bet: bool = False, dbx: Database = Depends(get_db)):
        rows = dbx.query("""SELECT p.* FROM paper_prediction p JOIN (SELECT match_id, market, selection, MAX(seq) seq
                            FROM paper_prediction GROUP BY 1,2,3) l ON l.seq=p.seq ORDER BY p.kickoff_utc""")
        out = []
        for r in rows:
            if not include_no_bet and r["status"] in ("NO_BET", "INSUFFICIENT_DATA"):
                continue
            pl = json.loads(r["payload"])
            m = dbx.query("SELECT home_team_id, away_team_id FROM match WHERE match_id=?", (r["match_id"],))
            out.append({"match_id": r["match_id"], "match": f"{team_name(dbx, m[0]['home_team_id'])} v {team_name(dbx, m[0]['away_team_id'])}" if m else r["match_id"],
                        "kickoff_utc": r["kickoff_utc"], "market": r["market"], "selection": r["selection"], "line": r["line"],
                        "odds": r["odds"], "model_prob": r["model_prob"], "prob_low": r["prob_low"], "prob_high": r["prob_high"],
                        "fair_prob": r["market_prob"], "edge": r["edge"], "ev": r["ev"], "data_quality": r["data_quality"],
                        "agreement": pl.get("agreement"), "status": r["status"], "reasons": json.loads(r["reasons"]),
                        "reason_text": pl.get("reason_text"), "stake_fraction": r["stake_fraction"]})
        return out

    @app.get("/odds")
    def odds(match_id: str, dbx: Database = Depends(get_db)):
        check_id(match_id)
        return dbx.query("SELECT * FROM odds_snapshot WHERE match_id=? ORDER BY available_at", (match_id,))

    @app.get("/models")
    def models(dbx: Database = Depends(get_db)):
        from sports_engine.models.champion import ModelRegistry
        cal_dir = s.path("paths.models_dir", "models") / "calibration"
        cals = {p.stem: json.loads(p.read_text(encoding="utf-8"))["selection"] for p in cal_dir.glob("*.json")} if cal_dir.exists() else {}
        return {"registry": ModelRegistry(dbx).list(), "calibrators": cals}

    @app.get("/backtests")
    def backtests(dbx: Database = Depends(get_db)):
        rows = dbx.query("SELECT run_id, experiment_id, created_at, summary, report_dir FROM backtest_run ORDER BY created_at DESC")
        for r in rows:
            r["summary"] = json.loads(r["summary"] or "{}")
            rp = Path(r.pop("report_dir")) / "report.json"
            r["interpretation"] = json.loads(rp.read_text(encoding="utf-8")).get("interpretation") if rp.exists() else None
        return rows

    @app.get("/experiments")
    def experiments(dbx: Database = Depends(get_db)):
        from sports_engine.experiments.registry import ExperimentRegistry
        reg = ExperimentRegistry(dbx)
        return {"stats": reg.all_stats(), "recent": reg.list(50)}

    @app.get("/bankroll")
    def bankroll(dbx: Database = Depends(get_db)):
        from sports_engine.paper.engine import PaperEngine
        return PaperEngine(s, dbx).status()

    @app.get("/clv")
    def clv(dbx: Database = Depends(get_db)):
        return dbx.query("""SELECT p.market, p.competition_id, COUNT(*) n, AVG(o.clv_price) mean_clv_price, AVG(o.clv_fair) mean_clv_fair
                            FROM paper_outcome o JOIN paper_prediction p ON p.prediction_id=o.prediction_id
                            WHERE p.stake_fraction > 0 GROUP BY 1,2""")

    @app.get("/slips")
    def slips(ids: str = Query(..., max_length=400, description="comma-separated paper prediction ids"),
              dbx: Database = Depends(get_db)):
        from sports_engine.correlation.slips import Leg, evaluate_slip
        legs = []
        for pid in [x.strip() for x in ids.split(",") if x.strip()]:
            check_id(pid)
            r = dbx.query("SELECT * FROM paper_prediction WHERE prediction_id=?", (pid,))
            if not r:
                raise HTTPException(404, f"unknown prediction {pid}")
            r = r[0]
            if not r["odds"]:
                raise HTTPException(422, f"{pid} has no odds; a slip cannot be priced")
            pl = json.loads(r["payload"])
            lh, la = pl.get("expected_goals") or [None, None]
            if not lh:
                raise HTTPException(422, f"{pid} has no score model")
            m = dbx.query("SELECT home_team_id, away_team_id, competition_id FROM match WHERE match_id=?", (r["match_id"],))[0]
            legs.append(Leg(r["match_id"], r["market"], r["selection"], r["odds"], r["model_prob"], lh, la, pl.get("rho", 0.0),
                            r["line"], m["home_team_id"], m["away_team_id"], m["competition_id"]))
        try:
            return evaluate_slip(legs, max_legs=int(s.get("risk.max_slip_legs", 5))).as_dict()
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/data-health")
    def data_health_ep(dbx: Database = Depends(get_db)):
        from sports_engine.reporting.daily import data_health
        return data_health(dbx)

    @app.get("/model-health")
    def model_health_ep(dbx: Database = Depends(get_db)):
        from sports_engine.reporting.daily import model_health
        return model_health(dbx)

    @app.get("/historical-data")
    def historical(dbx: Database = Depends(get_db)):
        from sports_engine.quality.coverage import historical_data_report
        return historical_data_report(dbx)

    @app.get("/coverage")
    def coverage(dbx: Database = Depends(get_db)):
        from sports_engine.quality.coverage import coverage_matrix
        cov = coverage_matrix(dbx)
        return cov.to_dict("records") if len(cov) else []

    @app.get("/research-lab")
    def research_lab(dbx: Database = Depends(get_db)):
        from sports_engine.experiments.registry import ExperimentRegistry
        return {"experiment_stats": ExperimentRegistry(dbx).all_stats(),
                "pipeline": "IDEA -> EXPERIMENT -> WALK-FORWARD -> CALIBRATION -> MARKET BENCHMARK -> ROBUSTNESS -> CHALLENGER -> PROMOTION",
                "holdout_start": s.get("holdout.start_date"),
                "rules": ["no promotion on ROI", "leakage suite must pass", "multiple testing is counted per family",
                          "final holdout access is logged and limited"]}

    @app.post("/journal", dependencies=[Depends(require_token)])
    def journal(note: str = Query(..., max_length=4000), prediction_id: str | None = Query(None, max_length=64),
                kind: str = Query("note", pattern="^(note|manual_bet|review)$"), dbx: Database = Depends(get_db)):
        from sports_engine.core.timeutils import iso, utcnow
        if prediction_id:
            check_id(prediction_id)
        dbx.execute("INSERT INTO journal_entry(created_at, prediction_id, kind, note) VALUES (?,?,?,?)",
                    (iso(utcnow()), prediction_id, kind, note))
        return {"ok": True}

    return app
