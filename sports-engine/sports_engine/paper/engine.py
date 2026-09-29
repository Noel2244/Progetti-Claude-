"""Live paper engine: out-of-sample predictions that can never be edited.

* predictions are appended to ``paper_prediction`` (UPDATE/DELETE blocked by
  SQLite triggers) and chained by hash (``prev_hash`` -> ``row_hash``), so any
  tampering outside SQLite is detectable with ``verify_chain()``;
* a new prediction for the same match/market/selection is only written when
  something changed (data snapshot, odds, model version); it references the
  version it supersedes;
* ``reconcile()`` appends outcomes (result, closing odds, CLV, P/L, loss);
* this data stream is kept separate from historical research data and is
  never used for tuning.

Nothing here can place a bet. Stakes are hypothetical paper fractions.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from sports_engine.calibration.calibrators import IdentityCalibrator, calibrator_from_dict
from sports_engine.core.config import Settings
from sports_engine.core.enums import DecisionStatus
from sports_engine.core.hashing import canonical_json, sha256_bytes, short_id, stable_hash
from sports_engine.core.logging import get_logger, log_event
from sports_engine.core.timeutils import ensure_utc, iso, utcnow
from sports_engine.database.db import Database, dumps
from sports_engine.decision.engine import REASONS, Candidate, DecisionConfig, decide
from sports_engine.decision.staking import RiskLimits, StakingConfig, apply_risk_limits, stake_fraction
from sports_engine.entity.competitions import get_competition
from sports_engine.features.team_features import FEATURE_VERSION, build_team_features
from sports_engine.market.clv import clv_fair, clv_price
from sports_engine.market.consensus import market_view
from sports_engine.models.registry import STATISTICAL_MODELS, model_factories
from sports_engine.models.score_matrix import DerivedMarkets
from sports_engine.pit.cutoffs import kickoff_or_none
from sports_engine.pit.store import HistoricalStore
from sports_engine.quality.scoring import composite
from sports_engine.uncertainty.agreement import combined_interval, model_agreement

log = get_logger("paper")
GENESIS = "GENESIS"
SEL_INDEX = {"H": 0, "D": 1, "A": 2}


def _row_hash(prev_hash: str, row: dict) -> str:
    return sha256_bytes((prev_hash + canonical_json(row)).encode("utf-8"))


class PaperEngine:
    def __init__(self, settings: Settings, db: Database):
        self.s = settings
        self.db = db

    # ---------------------------------------------------------------- helpers
    def _calibrator(self, model: str):
        path = self.s.path("paths.models_dir", "models") / "calibration" / f"{model}.json"
        if not path.exists():
            return IdentityCalibrator(), None, None
        doc = json.loads(path.read_text(encoding="utf-8"))
        return calibrator_from_dict(doc["calibrator"]), doc["calibrator"]["method"], doc.get("run_id")

    def _latest_versions(self) -> dict[tuple, dict]:
        rows = self.db.query("""SELECT p.* FROM paper_prediction p JOIN (
                                   SELECT match_id, market, selection, MAX(seq) AS seq FROM paper_prediction
                                   GROUP BY match_id, market, selection) l ON l.seq = p.seq""")
        return {(r["match_id"], r["market"], r["selection"]): r for r in rows}

    def _append(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        last = self.db.query("SELECT row_hash FROM paper_prediction ORDER BY seq DESC LIMIT 1")
        prev = last[0]["row_hash"] if last else GENESIS
        cols = None
        with self.db.transaction() as c:
            for r in rows:
                r = dict(r, prev_hash=prev)
                r["row_hash"] = _row_hash(prev, {k: v for k, v in r.items() if k not in ("row_hash",)})
                cols = cols or list(r.keys())
                c.execute(f"INSERT INTO paper_prediction({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                          tuple(r[k] for k in cols))
                prev = r["row_hash"]
        return len(rows)

    def _match_quality(self, fx, hist_h: int, hist_a: int, overdue: int, mv) -> tuple[float, dict]:
        comps = {
            "timestamp_quality": 1.0 if kickoff_or_none(fx.kickoff_utc) else 0.5,
            "completeness": min(1.0, min(hist_h, hist_a) / 30.0),
            "freshness": max(0.0, 1.0 - overdue / 10.0),
            "consistency": 1.0,
            "source_reliability": 0.7,
        }
        q = composite(comps)
        return q.score, q.as_dict()

    # ---------------------------------------------------------------- run
    def run(self, now: datetime | None = None, horizon_days: int | None = None,
            competitions: list[str] | None = None, primary: str | None = None) -> dict:
        now = ensure_utc(now or utcnow())
        comps = competitions or self.s.get("competitions", ["ITA1"])
        horizon = int(horizon_days or self.s.get("paper.horizon_days", 7))
        min_lead = timedelta(minutes=int(self.s.get("paper.min_minutes_before_kickoff", 30)))
        primary = primary or self.s.get("paper.primary_model", "dixon_coles")
        store = HistoricalStore.from_db(self.db, comps)
        snap = store.as_of(now)
        visible = set(snap.results()["match_id"])
        fx_all = store.fixtures(now - timedelta(days=30), now + timedelta(days=horizon), comps)
        fx_all = fx_all[~fx_all["match_id"].isin(visible)]
        kick = pd.to_datetime(fx_all["kickoff_utc"], utc=True)
        dates = pd.to_datetime(fx_all["match_date"])
        upcoming = fx_all[(kick.notna() & (kick > now + min_lead)) | (kick.isna() & (dates.dt.date > now.date()))]
        overdue = int(((kick.notna() & (kick < now - timedelta(hours=6))) | (kick.isna() & (dates.dt.date < now.date()))).sum())
        summary = {"run_at": iso(now), "competitions": comps, "snapshot": snap.fingerprint, "upcoming": int(len(upcoming)),
                   "overdue_results_in_data": overdue, "written": 0, "skipped_unchanged": 0, "status_counts": {}}
        if upcoming.empty:
            nxt = store.fixtures(now, now + timedelta(days=365), comps)
            nxt = nxt[~nxt["match_id"].isin(visible)]
            summary["next_fixture_date"] = str(nxt["match_date"].min()) if len(nxt) else None
            summary["message"] = f"no fixtures in the next {horizon} days"
            return summary
        fixtures = snap.fixtures(upcoming["match_id"])
        factories = model_factories(self.s)
        names = [n for n in ("climatology", "elo", "poisson_weighted", "dixon_coles", "market") if n in factories]
        preds: dict[str, dict] = {}
        versions: dict[str, str] = {}
        for n in names:
            model = factories[n]()
            model.fit(snap, comps)
            versions[n] = f"{model.version}+{stable_hash(model.params_dict(), 8)}"
            preds[n] = {p.match_id: p for p in model.predict(fixtures)}
        cal, cal_method, cal_run = self._calibrator(primary)
        feats = build_team_features(snap, fixtures, comps)
        dcfg, scfg, limits = DecisionConfig.from_settings(self.s), StakingConfig.from_settings(self.s), RiskLimits.from_settings(self.s)
        latest = self._latest_versions()
        new_rows, stake_inputs = [], []
        for fx in fixtures.itertuples(index=False):
            pp = preds.get(primary, {}).get(fx.match_id)
            if pp is None:
                continue
            raw = pp.probs
            calp = cal.transform(raw[None, :])[0]
            stat_vecs = {n: preds[n][fx.match_id].probs for n in STATISTICAL_MODELS if n in preds and fx.match_id in preds[n]}
            ag = model_agreement(stat_vecs)
            odds = snap.match_odds(fx.match_id, "1X2")
            mv = market_view(odds, fx.match_id, "1X2", method=self.s.get("decision.margin_method", "power"), as_of=now,
                             max_staleness_hours=float(self.s.get("point_in_time.max_odds_staleness_hours", 72)))
            dq, dq_detail = self._match_quality(fx, pp.home_matches or 0, pp.away_matches or 0, overdue, mv)
            ko = kickoff_or_none(fx.kickoff_utc)
            comp = get_competition(fx.competition_id)
            cutoffs = {"match_time": iso(ko) if ko else None, "prediction_timestamp": iso(now), "data_cutoff": iso(now),
                       "feature_cutoff": iso(now), "odds_cutoff": iso(now), "lineup_cutoff": None,
                       "model_run_time": iso(utcnow()), "timezone": comp.timezone}
            odds_fp = stable_hash([mv.best_odds.tolist() if mv.best_odds is not None else None,
                                   mv.consensus.tolist() if mv.consensus is not None else None], 16)
            markets = [("1X2", s, None, float(calp[SEL_INDEX[s]]), float(raw[SEL_INDEX[s]]), mv) for s in "HDA"]
            if pp.matrix is not None:
                dm = DerivedMarkets(pp.matrix)
                ou_odds = snap.match_odds(fx.match_id, "OU")
                ouv = market_view(ou_odds, fx.match_id, "OU", line=2.5, as_of=now) if len(ou_odds) else None
                markets += [("OU", "OVER", 2.5, dm.over(2.5), dm.over(2.5), ouv), ("OU", "UNDER", 2.5, dm.under(2.5), dm.under(2.5), ouv)]
            for market, sel, line, p_cal, p_raw, view in markets:
                is_1x2 = market == "1X2"
                sd_p = pp.sd.get(sel) if (pp.sd and is_1x2) else None
                sd_m = float(ag.per_selection_sd[SEL_INDEX[sel]]) if is_1x2 and ag.n_models > 1 else None
                lo, hi, _ = combined_interval(p_cal, sd_p, sd_m)
                best, book = (view.best(sel) if (view is not None and view.consensus is not None) else (None, None))
                c = decide(Candidate(
                    match_id=fx.match_id, market=market, selection=sel, line=line, model=primary, model_prob=p_cal,
                    raw_model_prob=p_raw, prob_low=lo, prob_high=hi,
                    market_fair_prob=view.prob(sel) if (view is not None and view.consensus is not None) else None,
                    market_raw_prob=(1 / best) if best else None, odds=best, bookmaker=book, data_quality=dq,
                    agreement_diff=ag.max_abs_diff if is_1x2 and ag.n_models > 1 else None,
                    home_matches=pp.home_matches, away_matches=pp.away_matches,
                    market_flags=list(view.flags) if view is not None else ["NO_ODDS"],
                    calibration_method=(cal_method if is_1x2 else None)), dcfg)
                key = (fx.match_id, market, sel)
                prev = latest.get(key)
                if prev and prev["snapshot_fingerprint"] == snap.fingerprint and prev["model_version"] == versions[primary] \
                        and json.loads(prev["payload"]).get("odds_fingerprint") == odds_fp:
                    summary["skipped_unchanged"] += 1
                    continue
                payload = {
                    "cutoffs": cutoffs, "odds_fingerprint": odds_fp,
                    "models": {n: dict(zip("HDA", map(float, preds[n][fx.match_id].probs))) for n in preds if fx.match_id in preds[n]},
                    "model_versions": versions, "calibration": {"method": cal_method, "run_id": cal_run},
                    "expected_goals": [pp.lambda_home, pp.lambda_away], "rho": pp.rho,
                    "top_scores": _top_scores(pp.matrix) if pp.matrix is not None else None,
                    "agreement": {"max_abs_diff": ag.max_abs_diff, "level": ag.level},
                    "market": {"n_books": view.n_books if view else 0, "margin": view.margin_median if view else None,
                               "flags": view.flags if view else ["NO_ODDS"]},
                    "data_quality": dq_detail, "features_fingerprint": feats.fingerprint,
                    "reason_text": [REASONS.get(r.split(":")[0], r) for r in c.reasons], "warnings": c.warnings,
                    "ev_conservative": c.ev_conservative, "ev_lower": c.ev_lower,
                }
                pid = short_id("pp", fx.match_id, market, sel, iso(now), snap.fingerprint, odds_fp)
                row = {
                    "prediction_id": pid, "created_at": iso(utcnow()), "prediction_timestamp": iso(now),
                    "data_cutoff": iso(now), "feature_cutoff": iso(now), "odds_cutoff": iso(now), "lineup_cutoff": None,
                    "match_id": fx.match_id, "competition_id": fx.competition_id, "kickoff_utc": iso(ko) if ko else None,
                    "model_name": primary, "model_version": versions[primary], "feature_version": FEATURE_VERSION,
                    "market": market, "selection": sel, "line": line, "model_prob": p_cal, "prob_low": lo, "prob_high": hi,
                    "market_prob": c.market_fair_prob, "odds": best, "bookmaker": book, "edge": c.edge, "ev": c.ev,
                    "data_quality": dq, "status": c.status.value, "reasons": dumps(c.reasons), "stake_fraction": 0.0,
                    "snapshot_fingerprint": snap.fingerprint, "supersedes": prev["prediction_id"] if prev else None,
                    "payload": dumps(payload),
                }
                if c.status in (DecisionStatus.CANDIDATE, DecisionStatus.STRONG_CANDIDATE):
                    p_cons = c.market_fair_prob + dcfg.shrink_to_market * (p_cal - c.market_fair_prob)
                    stake_inputs.append({"key": pid, "match_id": fx.match_id, "day": str(fx.match_date), "league": fx.competition_id,
                                         "home_team": fx.home_team_id, "away_team": fx.away_team_id,
                                         "stake_fraction": stake_fraction(p_cons, best, scfg), "ev_conservative": c.ev_conservative})
                new_rows.append(row)
        for s in apply_risk_limits(stake_inputs, limits):
            for r in new_rows:
                if r["prediction_id"] == s["key"]:
                    r["stake_fraction"] = float(s["stake_fraction"])
        summary["written"] = self._append(new_rows)
        summary["status_counts"] = pd.Series([r["status"] for r in new_rows]).value_counts().to_dict() if new_rows else {}
        summary["primary_model"] = primary
        summary["calibration"] = cal_method or "none (no validated calibrator yet)"
        log_event(log, "paper run", **{k: v for k, v in summary.items() if k != "status_counts"})
        return summary

    # ---------------------------------------------------------------- reconcile
    def reconcile(self, now: datetime | None = None) -> dict:
        now = ensure_utc(now or utcnow())
        pending = self.db.query("""SELECT p.* FROM paper_prediction p LEFT JOIN paper_outcome o ON o.prediction_id = p.prediction_id
                                   WHERE o.id IS NULL""")
        if not pending:
            return {"reconciled": 0, "pending": 0}
        comps = sorted({r["competition_id"] for r in pending})
        store = HistoricalStore.from_db(self.db, comps)
        snap = store.as_of(now)
        res = snap.results().set_index("match_id")
        done = 0
        with self.db.transaction() as c:
            for r in pending:
                if r["match_id"] not in res.index:
                    continue
                m = res.loc[r["match_id"]]
                hg, ag = int(m["home_goals"]), int(m["away_goals"])
                if r["market"] == "1X2":
                    happened = {"H": hg > ag, "D": hg == ag, "A": hg < ag}[r["selection"]]
                else:
                    tot = hg + ag
                    happened = tot > r["line"] if r["selection"] == "OVER" else tot < r["line"]
                p = float(r["model_prob"])
                staked = float(r["stake_fraction"] or 0) > 0
                close = store.closing_odds_for(r["match_id"])
                close = close[(close["market"] == r["market"]) & (close["selection"] == r["selection"])]
                close_price = float(close["odds"].median()) if len(close) else None
                cmv = market_view(store.closing_odds_for(r["match_id"]), r["match_id"], r["market"],
                                  line=r["line"] if r["market"] != "1X2" else None) if len(close) else None
                close_fair = cmv.prob(r["selection"]) if cmv is not None and cmv.consensus is not None else None
                units = float(r["stake_fraction"] or 0) * 100.0
                pnl = (units * (r["odds"] - 1) if happened else -units) if staked else 0.0
                c.execute(
                    """INSERT INTO paper_outcome(prediction_id, reconciled_at, home_goals, away_goals, outcome, closing_odds,
                       closing_fair_prob, clv_price, clv_fair, pnl_units, log_loss, brier) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["prediction_id"], iso(now), hg, ag,
                     ("WIN" if happened else "LOSE") if staked else ("NOT_BET_HIT" if happened else "NOT_BET_MISS"),
                     close_price, close_fair,
                     clv_price(r["odds"], close_price) if (r["odds"] and close_price) else None,
                     clv_fair(r["odds"], close_fair) if (r["odds"] and close_fair) else None,
                     pnl, float(-np.log(max(1e-15, p if happened else 1 - p))), float((p - happened) ** 2)))
                done += 1
        return {"reconciled": done, "pending": len(pending) - done}

    # ---------------------------------------------------------------- status / integrity
    def status(self) -> dict:
        n = self.db.scalar("SELECT COUNT(*) FROM paper_prediction") or 0
        last = self.db.df("""SELECT p.*, o.outcome, o.pnl_units, o.log_loss, o.brier, o.clv_price, o.clv_fair
                             FROM paper_prediction p JOIN (SELECT match_id, market, selection, MAX(seq) seq FROM paper_prediction
                             GROUP BY 1,2,3) l ON l.seq = p.seq LEFT JOIN paper_outcome o ON o.prediction_id = p.prediction_id""")
        out = {"predictions_total": int(n), "latest_versions": int(len(last)),
               "status_counts": last["status"].value_counts().to_dict() if len(last) else {},
               "resolved": int(last["outcome"].notna().sum()) if len(last) else 0}
        res = last[last["outcome"].notna()] if len(last) else last
        if len(res):
            one = res[res["market"] == "1X2"]
            out["mean_log_loss_binary"] = float(one["log_loss"].mean()) if len(one) else None
            out["mean_brier_binary"] = float(one["brier"].mean()) if len(one) else None
            bets = res[res["stake_fraction"] > 0]
            out["paper_bets"] = int(len(bets))
            if len(bets):
                out["paper_pnl_units"] = float(bets["pnl_units"].sum())
                out["mean_clv_price"] = float(bets["clv_price"].dropna().mean()) if bets["clv_price"].notna().any() else None
                out["bankroll"] = float(self.s.get("paper.starting_bankroll", 1000.0)) * (1 + out["paper_pnl_units"] / 100.0)
            out["note"] = "Too few resolved predictions for statistical conclusions." if len(res) < 300 else None
        out["chain_ok"] = not self.verify_chain()
        return out

    def verify_chain(self) -> list[str]:
        problems, prev = [], GENESIS
        for r in self.db.query("SELECT * FROM paper_prediction ORDER BY seq"):
            body = {k: v for k, v in r.items() if k not in ("seq", "row_hash")}
            if r["prev_hash"] != prev:
                problems.append(f"seq {r['seq']}: broken link")
            if _row_hash(prev, body) != r["row_hash"]:
                problems.append(f"seq {r['seq']}: content hash mismatch")
            prev = r["row_hash"]
        return problems


def _top_scores(matrix: np.ndarray, k: int = 6) -> list[list]:
    flat = [(float(matrix[i, j]), i, j) for i in range(matrix.shape[0]) for j in range(matrix.shape[1])]
    return [[f"{i}-{j}", round(p, 4)] for p, i, j in sorted(flat, reverse=True)[:k]]
