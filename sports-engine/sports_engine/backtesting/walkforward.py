"""Walk-forward (expanding-window) backtest with point-in-time integrity.

For every fixture the decision time is fixed first (``DecisionTimingPolicy``);
fixtures sharing a decision time form a batch; every model is fitted on
``store.as_of(decision_time)`` only (goal models may reuse a fit up to
``refit_days`` old - reusing an *older* fit can never leak). Nothing in this
module reads results except the evaluation step at the very end.

Calibration is sequential: predictions for season s are calibrated with a
calibrator selected and fitted on out-of-sample predictions from seasons < s.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from sports_engine.calibration.calibrators import IdentityCalibrator, select_calibrator
from sports_engine.calibration.metrics import (
    brier_per_obs,
    log_loss_per_obs,
    multiclass_report,
    paired_bootstrap,
    rps_per_obs,
)
from sports_engine.core.errors import HoldoutAccessError
from sports_engine.core.logging import get_logger, log_event
from sports_engine.decision.engine import Candidate, DecisionConfig, decide
from sports_engine.decision.staking import RiskLimits, StakingConfig, apply_risk_limits, stake_fraction
from sports_engine.entity.competitions import get_competition
from sports_engine.market.clv import clv_fair, clv_price
from sports_engine.market.consensus import market_view
from sports_engine.market.margin import remove_margin
from sports_engine.models.base import MatchPrediction
from sports_engine.models.registry import STATISTICAL_MODELS
from sports_engine.pit.cutoffs import DecisionTimingPolicy, kickoff_or_none
from sports_engine.pit.store import HistoricalStore
from sports_engine.uncertainty.agreement import combined_interval, model_agreement

log = get_logger("backtest")
OUTCOME_INDEX = {"H": 0, "D": 1, "A": 2}


@dataclass
class BacktestConfig:
    competitions: list[str]
    test_start: date
    test_end: date
    models: list[str] = field(default_factory=lambda: ["climatology", "elo", "poisson", "poisson_weighted", "dixon_coles", "market"])
    primary_model: str = "dixon_coles"
    burn_in_start: date | None = None          # predictions made (OOS) but only used to train calibrators
    refit_days: int = 7
    lead_minutes: int = 60
    calibrate: bool = True
    calibration_candidates: tuple[str, ...] = ("identity", "temperature", "dirichlet", "ovr_isotonic")
    calibration_min_train: int = 600
    calibration_min_improvement: float = 0.002
    holdout_start: date | None = None
    use_holdout: bool = False
    margin_method: str = "power"
    max_odds_staleness_hours: float = 96.0
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    staking: StakingConfig = field(default_factory=StakingConfig)
    risk: RiskLimits = field(default_factory=RiskLimits)
    bootstrap: int = 1000
    seed: int = 42

    def as_dict(self) -> dict:
        d = asdict(self)
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in d.items()}


@dataclass
class BacktestResult:
    config: dict
    predictions: pd.DataFrame
    metrics: dict
    per_season: pd.DataFrame
    comparisons: dict
    calibration: dict
    bets: pd.DataFrame
    betting: dict
    notes: list[str]
    runtime_seconds: float


class WalkForwardBacktest:
    def __init__(self, store: HistoricalStore, config: BacktestConfig, factories: dict):
        self.store = store
        self.cfg = config
        self.factories = factories
        self.notes: list[str] = []

    # ------------------------------------------------------------ schedule
    def _schedule(self) -> pd.DataFrame:
        cfg = self.cfg
        start = cfg.burn_in_start or cfg.test_start
        end = cfg.test_end
        if cfg.holdout_start is not None and end >= cfg.holdout_start:
            if not cfg.use_holdout:
                end = cfg.holdout_start - timedelta(days=1)
                self.notes.append(f"test window clipped to {end} to protect the final holdout (starts {cfg.holdout_start})")
        if cfg.use_holdout and cfg.holdout_start is None:
            raise HoldoutAccessError("use_holdout requested but no holdout configured")
        fx = self.store.fixtures(datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time()),
                                 cfg.competitions)
        done = set(self.store.outcomes(fx["match_id"])["match_id"])
        fx = fx[fx["match_id"].isin(done)].copy()   # only matches that were actually played can be evaluated
        policy = DecisionTimingPolicy(cfg.lead_minutes)
        pre = self.store._odds
        pre = pre[(pre["snapshot_type"] == "PRE_MATCH") & pre["match_id"].isin(set(fx["match_id"]))]
        odds_times = pre.groupby("match_id")["available_at"].apply(lambda s: sorted(set(s))).to_dict() if len(pre) else {}
        rows = []
        for r in fx.itertuples(index=False):
            comp = get_competition(r.competition_id)
            ko = kickoff_or_none(r.kickoff_utc)
            c = policy.cutoffs(ko, date.fromisoformat(r.match_date), comp.timezone,
                               [t.to_pydatetime() for t in odds_times.get(r.match_id, [])])
            rows.append({"match_id": r.match_id, "decision_time": pd.Timestamp(c.prediction_timestamp), "policy": c.policy,
                         "kickoff_utc": ko, "match_date": r.match_date, "season": r.season, "season_start_year": r.season_start_year,
                         "competition_id": r.competition_id, "home_team_id": r.home_team_id, "away_team_id": r.away_team_id,
                         "is_burn_in": date.fromisoformat(r.match_date) < cfg.test_start})
        sched = pd.DataFrame(rows)
        if sched.empty:
            return sched
        return sched.sort_values(["decision_time", "match_id"]).reset_index(drop=True)

    # ------------------------------------------------------------ predict
    def _predict_all(self, sched: pd.DataFrame) -> pd.DataFrame:
        cfg = self.cfg
        models = {name: self.factories[name]() for name in cfg.models}
        last_fit: dict[str, pd.Timestamp] = {}
        records = []
        n_batches = sched["decision_time"].nunique()
        t_start = time.time()
        for b_i, (t, batch) in enumerate(sched.groupby("decision_time", sort=True)):
            if b_i % 250 == 0:
                log_event(log, "backtest progress", batch=b_i, of=int(n_batches), decision_time=str(t),
                          elapsed_s=round(time.time() - t_start, 1))
            snap = self.store.as_of(t.to_pydatetime())
            fixtures = snap.fixtures(batch["match_id"])
            for name, model in models.items():
                needs = name not in last_fit or name in ("elo", "market", "climatology") \
                    or (t - last_fit[name]) >= pd.Timedelta(days=cfg.refit_days)
                if needs:
                    model.fit(snap, cfg.competitions)
                    last_fit[name] = t
                for p in model.predict(fixtures):
                    records.append(self._record(p, t, snap.fingerprint, last_fit[name]))
        return pd.DataFrame(records)

    @staticmethod
    def _record(p: MatchPrediction, t: pd.Timestamp, fingerprint: str, fitted_at: pd.Timestamp) -> dict:
        d = {"match_id": p.match_id, "model": p.model, "model_version": p.model_version,
             "p_H": p.p_home, "p_D": p.p_draw, "p_A": p.p_away, "lambda_home": p.lambda_home, "lambda_away": p.lambda_away,
             "rho": p.rho, "decision_time": t, "model_fitted_as_of": fitted_at, "snapshot": fingerprint,
             "home_matches": p.home_matches, "away_matches": p.away_matches}
        for k in "HDA":
            d[f"sd_{k}"] = p.sd[k] if p.sd else np.nan
            d[f"lo_{k}"] = p.interval[k][0] if p.interval else np.nan
            d[f"hi_{k}"] = p.interval[k][1] if p.interval else np.nan
        if p.matrix is not None:
            from sports_engine.models.score_matrix import DerivedMarkets
            dm = DerivedMarkets(p.matrix)
            d["p_OVER25"] = dm.over(2.5)
            d["p_BTTS"] = dm.btts()
        return d

    # ------------------------------------------------------------ calibrate
    def _calibrate(self, preds: pd.DataFrame, sched: pd.DataFrame, outcomes: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
        cfg = self.cfg
        preds = preds.merge(sched[["match_id", "season_start_year"]], on="match_id", how="left")
        preds = preds.merge(outcomes[["match_id", "y"]], on="match_id", how="left")
        for k in "HDA":
            preds[f"pc_{k}"] = preds[f"p_{k}"]
        preds["calibration"] = "identity"
        report: dict = {}
        if not cfg.calibrate:
            return preds, report
        for model, g in preds.groupby("model"):
            if model == "market":
                continue  # the market is the benchmark; it is not recalibrated
            report[model] = {}
            for season in sorted(g["season_start_year"].unique()):
                past = g[g["season_start_year"] < season]
                cur_idx = g.index[g["season_start_year"] == season]
                if past["season_start_year"].nunique() < 2:
                    report[model][int(season)] = {"method": "identity", "reason": "no prior out-of-sample seasons"}
                    preds.loc[cur_idx, "calibration"] = "none"
                    continue
                # validate on the two most recent prior seasons (one season is too noisy to choose a method)
                seasons_prior = sorted(past["season_start_year"].unique())
                val_seasons = seasons_prior[-2:] if len(seasons_prior) >= 4 else seasons_prior[-1:]
                tr = past[~past["season_start_year"].isin(val_seasons)]
                va = past[past["season_start_year"].isin(val_seasons)]
                P = lambda df: df[["p_H", "p_D", "p_A"]].to_numpy()
                choice = select_calibrator(P(tr), tr["y"].to_numpy(), P(va), va["y"].to_numpy(),
                                           cfg.calibration_candidates, cfg.calibration_min_improvement, cfg.calibration_min_train)
                cal = choice.calibrator
                if choice.method != "identity":
                    cal = type(cal)().fit(P(past), past["y"].to_numpy())  # refit on all prior OOS predictions
                Q = cal.transform(P(g.loc[cur_idx]))
                preds.loc[cur_idx, ["pc_H", "pc_D", "pc_A"]] = Q
                preds.loc[cur_idx, "calibration"] = choice.method
                report[model][int(season)] = {"method": choice.method, "reason": choice.reason,
                                              "validation_logloss": {k: round(v, 5) for k, v in choice.validation.items()}}
        return preds, report

    # ------------------------------------------------------------ evaluate
    def _evaluate(self, preds: pd.DataFrame) -> tuple[dict, pd.DataFrame, dict]:
        cfg = self.cfg
        test = preds[~preds["is_burn_in"]]
        metrics, per_season_rows = {}, []
        for model, g in test.groupby("model"):
            for col, label in (("p", "raw"), ("pc", "calibrated")):
                if label == "calibrated" and model == "market":
                    continue
                P = g[[f"{col}_H", f"{col}_D", f"{col}_A"]].to_numpy()
                rep = multiclass_report(P, g["y"].to_numpy())
                metrics[f"{model}:{label}"] = {k: v for k, v in rep.items() if k != "classes"} | {
                    "classes": {c: {kk: vv for kk, vv in d.items() if kk != "reliability"} for c, d in rep["classes"].items()},
                    "reliability": {c: d["reliability"] for c, d in rep["classes"].items()},
                }
            for s, gs in g.groupby("season_start_year"):
                P = gs[["pc_H", "pc_D", "pc_A"]].to_numpy()
                y = gs["y"].to_numpy()
                per_season_rows.append({"model": model, "season": int(s), "n": len(gs),
                                        "log_loss": float(log_loss_per_obs(P, y).mean()),
                                        "brier": float(brier_per_obs(P, y).mean()), "rps": float(rps_per_obs(P, y).mean())})
        per_season = pd.DataFrame(per_season_rows)
        # paired comparisons on the common set of matches (bootstrap by match-day blocks)
        comps = {}
        wide = test.pivot_table(index="match_id", columns="model", values="ll", aggfunc="first")
        blocks_map = test.drop_duplicates("match_id").set_index("match_id")["decision_time"].dt.strftime("%Y-%W")
        refs = [r for r in ("climatology", "elo", "market") if r in wide.columns]
        for m in wide.columns:
            for ref in refs:
                if m == ref:
                    continue
                both = wide[[m, ref]].dropna()
                if len(both) < 30:
                    continue
                comps[f"{m}_vs_{ref}"] = paired_bootstrap(both[m].to_numpy(), both[ref].to_numpy(), cfg.bootstrap, cfg.seed,
                                                          blocks_map.reindex(both.index).to_numpy())
        return metrics, per_season, comps

    # ------------------------------------------------------------ betting simulation
    def _simulate_bets(self, preds: pd.DataFrame, sched: pd.DataFrame, outcomes: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
        cfg = self.cfg
        if "market" not in cfg.models or (preds["model"] == "market").sum() == 0:
            return pd.DataFrame(), {"available": False, "reason": "no market odds in the data for the test window"}
        test = preds[~preds["is_burn_in"]]
        prim = test[test["model"] == cfg.primary_model].set_index("match_id")
        stat = test[test["model"].isin(STATISTICAL_MODELS)]
        stat_by_match = {mid: g for mid, g in stat.groupby("match_id")}
        sched_i = sched.set_index("match_id")
        out_i = outcomes.set_index("match_id")
        rows = []
        for mid, pr in prim.iterrows():
            srow = sched_i.loc[mid]
            snap = self.store.as_of(srow["decision_time"].to_pydatetime())
            odds = snap.match_odds(mid, "1X2")
            mv = market_view(odds, mid, "1X2", method=cfg.margin_method, as_of=snap.as_of,
                             max_staleness_hours=cfg.max_odds_staleness_hours)
            ag = model_agreement({m: g[["pc_H", "pc_D", "pc_A"]].to_numpy()[0] for m, g in stat_by_match.get(mid, pd.DataFrame()).groupby("model")}) \
                if mid in stat_by_match else None
            y = int(out_i.loc[mid, "y"])
            close = self.store.closing_odds_for(mid)
            close = close[close["market"] == "1X2"]
            for k in "HDA":
                p_cal = float(pr[f"pc_{k}"])
                lo, hi, _ = combined_interval(p_cal, pr.get(f"sd_{k}"), float(ag.per_selection_sd[OUTCOME_INDEX[k]]) if ag else None)
                best, book = mv.best(k) if mv.consensus is not None else (None, None)
                cand = Candidate(
                    match_id=mid, market="1X2", selection=k, line=None, model=cfg.primary_model,
                    model_prob=p_cal, raw_model_prob=float(pr[f"p_{k}"]), prob_low=lo, prob_high=hi,
                    market_fair_prob=mv.prob(k), market_raw_prob=(1.0 / best if best else None), odds=best, bookmaker=book,
                    data_quality=None,  # match-level DQ is applied in live mode; not fabricated here
                    agreement_diff=ag.max_abs_diff if ag else None,
                    home_matches=int(pr["home_matches"]) if pd.notna(pr["home_matches"]) else None,
                    away_matches=int(pr["away_matches"]) if pd.notna(pr["away_matches"]) else None,
                    market_flags=list(mv.flags), calibration_method=pr["calibration"] if pr["calibration"] != "none" else None,
                )
                decide(cand, cfg.decision)
                p_cons = None if cand.market_fair_prob is None else cand.market_fair_prob + cfg.decision.shrink_to_market * (p_cal - cand.market_fair_prob)
                frac = stake_fraction(p_cons, best, cfg.staking) if cand.status.value in ("CANDIDATE", "STRONG_CANDIDATE") else 0.0
                c_odds = close[(close["selection"] == k)]
                close_book = c_odds[c_odds["bookmaker"] == book]["odds"] if book else pd.Series(dtype=float)
                close_price = float(close_book.iloc[-1]) if len(close_book) else (float(c_odds["odds"].median()) if len(c_odds) else None)
                close_fair = None
                cmv = market_view(close, mid, "1X2", method=cfg.margin_method) if len(close) else None
                if cmv is not None and cmv.consensus is not None:
                    close_fair = cmv.prob(k)
                rows.append({
                    "match_id": mid, "day": srow["decision_time"].date().isoformat(), "league": srow["competition_id"],
                    "home_team": srow["home_team_id"], "away_team": srow["away_team_id"], "season_start_year": srow["season_start_year"],
                    "selection": k, "status": cand.status.value, "reasons": ";".join(cand.reasons), "model_prob": p_cal,
                    "raw_model_prob": float(pr[f"p_{k}"]), "prob_low": lo, "market_prob": cand.market_fair_prob,
                    "odds": best, "bookmaker": book, "edge": cand.edge, "ev": cand.ev, "ev_conservative": cand.ev_conservative,
                    "ev_lower": cand.ev_lower, "stake_fraction": frac, "won": int(OUTCOME_INDEX[k] == y),
                    "closing_odds": close_price, "closing_fair_prob": close_fair,
                    "clv_price": clv_price(best, close_price) if (best and close_price) else None,
                    "clv_fair": clv_fair(best, close_fair) if (best and close_fair) else None,
                    "n_books": mv.n_books,
                })
        bets = pd.DataFrame(rows)
        if bets.empty:
            return bets, {"available": False, "reason": "no candidates"}
        sel = bets[bets["stake_fraction"] > 0].to_dict("records")
        limited = pd.DataFrame(apply_risk_limits(sel, cfg.risk)) if sel else pd.DataFrame(columns=list(bets.columns) + ["risk_notes"])
        bets = bets.drop(columns=[]).merge(
            limited[["match_id", "selection", "stake_fraction"]].rename(columns={"stake_fraction": "stake_after_limits"}),
            on=["match_id", "selection"], how="left")
        bets["stake_after_limits"] = bets["stake_after_limits"].fillna(0.0)
        bets["stake_units"] = bets["stake_after_limits"] * 100.0     # units of 1% starting bankroll
        bets["pnl_units"] = np.where(bets["stake_units"] > 0,
                                     np.where(bets["won"] == 1, bets["stake_units"] * (bets["odds"] - 1), -bets["stake_units"]), 0.0)
        return bets, summarise_bets(bets)

    # ------------------------------------------------------------ run
    def run(self) -> BacktestResult:
        t0 = time.time()
        sched = self._schedule()
        if sched.empty:
            raise ValueError("no finished fixtures in the requested window")
        outcomes = self.store.outcomes(sched["match_id"]).copy()
        outcomes["y"] = np.where(outcomes["home_goals"] > outcomes["away_goals"], 0,
                                 np.where(outcomes["home_goals"] == outcomes["away_goals"], 1, 2))
        disputed = set(outcomes[outcomes["score_disputed"] == 1]["match_id"])
        if disputed:
            self.notes.append(f"{len(disputed)} match(es) with disputed scores excluded from evaluation")
        log_event(log, "backtest schedule", fixtures=len(sched), batches=int(sched["decision_time"].nunique()))
        preds = self._predict_all(sched)
        preds = preds.merge(sched[["match_id", "is_burn_in", "policy"]], on="match_id", how="left")
        preds, cal_report = self._calibrate(preds, sched, outcomes)
        preds = preds[~preds["match_id"].isin(disputed)].copy()
        P = preds[["pc_H", "pc_D", "pc_A"]].to_numpy()
        preds["ll"] = log_loss_per_obs(P, preds["y"].to_numpy().astype(int))
        metrics, per_season, comps = self._evaluate(preds)
        bets, betting = self._simulate_bets(preds, sched, outcomes[~outcomes["match_id"].isin(disputed)])
        counts = preds[~preds["is_burn_in"]].groupby("model")["match_id"].nunique().to_dict()
        metrics["_coverage"] = {"fixtures_scheduled": int((~sched["is_burn_in"]).sum()), "predictions_per_model": counts,
                                "decision_policies": sched[~sched["is_burn_in"]]["policy"].value_counts().to_dict()}
        return BacktestResult(self.cfg.as_dict(), preds, metrics, per_season, comps, cal_report, bets, betting,
                              self.notes, round(time.time() - t0, 1))


def summarise_bets(bets: pd.DataFrame) -> dict:
    placed = bets[bets["stake_units"] > 0]
    status_counts = bets["status"].value_counts().to_dict()
    reason_counts: dict[str, int] = {}
    for rs in bets["reasons"]:
        for r in filter(None, str(rs).split(";")):
            code = r.split(":")[0]
            reason_counts[code] = reason_counts.get(code, 0) + 1
    out = {"available": True, "selections_evaluated": int(len(bets)), "status_counts": status_counts,
           "no_bet_reasons": dict(sorted(reason_counts.items(), key=lambda x: -x[1])), "bets": int(len(placed))}
    if len(placed):
        staked = float(placed["stake_units"].sum())
        pnl = placed.sort_values("day")["pnl_units"].cumsum()
        dd = float((pnl.cummax() - pnl).max())
        out.update({
            "wins": int(placed["won"].sum()), "losses": int((placed["won"] == 0).sum()),
            "staked_units": staked, "profit_units": float(placed["pnl_units"].sum()),
            "yield": float(placed["pnl_units"].sum() / staked) if staked else None,
            "max_drawdown_units": dd,
            "mean_odds": float(placed["odds"].mean()),
            "mean_model_prob": float(placed["model_prob"].mean()),
            "hit_rate": float(placed["won"].mean()),
            "expected_hit_rate": float(placed["model_prob"].mean()),
            "mean_clv_price": float(placed["clv_price"].dropna().mean()) if placed["clv_price"].notna().any() else None,
            "mean_clv_fair": float(placed["clv_fair"].dropna().mean()) if placed["clv_fair"].notna().any() else None,
            "share_beating_close": float((placed["clv_price"].dropna() > 0).mean()) if placed["clv_price"].notna().any() else None,
        })
        # bootstrap CI of yield (bets resampled) - sample-size awareness
        rng = np.random.default_rng(0)
        arr = placed[["pnl_units", "stake_units"]].to_numpy()
        idx = rng.integers(0, len(arr), size=(2000, len(arr)))
        ys = arr[idx, 0].sum(axis=1) / arr[idx, 1].sum(axis=1)
        out["yield_ci95"] = [float(np.percentile(ys, 2.5)), float(np.percentile(ys, 97.5))]
    return out
