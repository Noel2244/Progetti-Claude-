"""Edge, EV and the abstention (NO BET) engine.

EDGE = model_probability - market_fair_probability
EV   = p * (odds - 1) - (1 - p)  = p * odds - 1

The decision layer is deliberately conservative. Every status comes with the
list of reasons that produced it, and those reasons are stored for later analysis.
"NO BET" is a successful output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from sports_engine.core.enums import DecisionStatus

REASONS = {
    "NO_MARKET_ODDS": "no market odds available at decision time",
    "INCOMPLETE_MARKET": "market prices incomplete",
    "STALE_ODDS": "odds older than the staleness limit",
    "OUTLIER_BEST_PRICE": "best price far from consensus (possible stale/erroneous quote)",
    "SINGLE_BOOK": "only one bookmaker - no consensus",
    "NEGATIVE_EV": "expected value is not positive",
    "EV_BELOW_THRESHOLD": "expected value below threshold",
    "EDGE_BELOW_THRESHOLD": "edge vs fair market probability below threshold",
    "EDGE_CONSUMED_BY_MARGIN": "model beats the fair (margin-free) price but not the actual price: the apparent edge disappears after the bookmaker margin",
    "EDGE_REMOVED_BY_CALIBRATION": "the raw model showed value but the calibrated probability does not: the apparent edge disappears after calibration",
    "EDGE_NOT_ROBUST_TO_UNCERTAINTY": "EV is not positive at the conservative (market-shrunk) probability",
    "EV_LOWER_BOUND_NOT_POSITIVE": "EV at the lower uncertainty bound is not positive",
    "MODEL_DISAGREEMENT": "statistical models disagree beyond the limit",
    "LOW_DATA_QUALITY": "data quality below the minimum",
    "INSUFFICIENT_TEAM_HISTORY": "too few recent matches for at least one team",
    "ODDS_OUT_OF_RANGE": "odds outside the range where calibration is trusted",
    "CALIBRATION_UNAVAILABLE": "no validated calibration for this model yet",
    "LINEUP_UNKNOWN": "lineups not known at decision time (warning; conservative thresholds apply)",
    "MODEL_UNAVAILABLE": "model could not produce a prediction",
    "DRIFT_ALERT": "model/calibration drift alert active",
    "MODEL_NOT_VALIDATED_VS_MARKET": "the model has not shown out-of-sample information beyond the market (market-benchmark gate not passed), so apparent value is not trusted",
}


def expected_value(p: float, odds: float) -> float:
    return p * odds - 1.0


@dataclass
class DecisionConfig:
    min_edge: float = 0.02
    min_ev: float = 0.03
    shrink_to_market: float = 0.5
    max_model_disagreement: float = 0.08
    min_data_quality: float = 0.60
    min_team_matches: int = 8
    min_odds: float = 1.30
    max_odds: float = 6.00
    strong_requires_positive_ev_lower: bool = True

    @classmethod
    def from_settings(cls, settings) -> "DecisionConfig":
        d = settings.get("decision", {}) or {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Candidate:
    match_id: str
    market: str
    selection: str
    line: float | None
    model: str
    model_prob: float                # calibrated
    raw_model_prob: float | None
    prob_low: float | None
    prob_high: float | None
    market_fair_prob: float | None
    market_raw_prob: float | None
    odds: float | None
    bookmaker: str | None
    data_quality: float | None
    agreement_diff: float | None
    home_matches: int | None
    away_matches: int | None
    market_flags: list[str] = field(default_factory=list)
    calibration_method: str | None = None
    drift_alert: bool = False
    # True only when the model passed the market-benchmark promotion gate (betting-eligible champion).
    # Backtests set it True to evaluate decisions hypothetically; live paper mode reads the registry.
    model_validated_vs_market: bool = True
    # outputs
    edge: float | None = None
    ev: float | None = None
    ev_raw: float | None = None
    ev_conservative: float | None = None
    ev_lower: float | None = None
    status: DecisionStatus = DecisionStatus.NO_BET
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["reason_text"] = [REASONS.get(r.split(":")[0], r) for r in self.reasons]
        return d


def decide(c: Candidate, cfg: DecisionConfig) -> Candidate:
    reasons: list[str] = []
    warnings: list[str] = ["LINEUP_UNKNOWN"]
    insufficient = False
    if c.model_prob is None or not np.isfinite(c.model_prob):
        c.status, c.reasons = DecisionStatus.INSUFFICIENT_DATA, ["MODEL_UNAVAILABLE"]
        return c
    if c.odds is None or c.market_fair_prob is None:
        reasons.append("NO_MARKET_ODDS" if not c.market_flags else c.market_flags[0].split(":")[0])
        insufficient = True
    if c.home_matches is not None and c.away_matches is not None and min(c.home_matches, c.away_matches) < cfg.min_team_matches:
        reasons.append("INSUFFICIENT_TEAM_HISTORY")
        insufficient = True
    if c.data_quality is not None and c.data_quality < cfg.min_data_quality:
        reasons.append("LOW_DATA_QUALITY")
        insufficient = True
    if insufficient:
        c.status, c.reasons, c.warnings = DecisionStatus.INSUFFICIENT_DATA, reasons, warnings
        return c

    c.edge = c.model_prob - c.market_fair_prob
    c.ev = expected_value(c.model_prob, c.odds)
    c.ev_raw = expected_value(c.raw_model_prob, c.odds) if c.raw_model_prob is not None else None
    p_cons = c.market_fair_prob + cfg.shrink_to_market * (c.model_prob - c.market_fair_prob)
    c.ev_conservative = expected_value(p_cons, c.odds)
    c.ev_lower = expected_value(c.prob_low, c.odds) if c.prob_low is not None else None

    hard: list[str] = []
    soft: list[str] = []
    for f in c.market_flags:
        code = f.split(":")[0]
        if code in ("STALE_ODDS", "OUTLIER_BEST_PRICE"):
            hard.append(f)
        elif code == "SINGLE_BOOK":
            soft.append(f)
    if c.ev <= 0:
        hard.append("NEGATIVE_EV")
        if c.edge > 0:
            hard.append("EDGE_CONSUMED_BY_MARGIN")
        if c.ev_raw is not None and c.ev_raw > 0:
            hard.append("EDGE_REMOVED_BY_CALIBRATION")
    else:
        if c.ev < cfg.min_ev:
            soft.append("EV_BELOW_THRESHOLD")
        if c.edge < cfg.min_edge:
            soft.append("EDGE_BELOW_THRESHOLD")
        if c.ev_conservative <= 0:
            soft.append("EDGE_NOT_ROBUST_TO_UNCERTAINTY")
    if not (cfg.min_odds <= c.odds <= cfg.max_odds):
        hard.append("ODDS_OUT_OF_RANGE")
    if c.agreement_diff is not None and c.agreement_diff > cfg.max_model_disagreement:
        hard.append("MODEL_DISAGREEMENT")
    if c.drift_alert:
        hard.append("DRIFT_ALERT")
    if not c.model_validated_vs_market:
        hard.append("MODEL_NOT_VALIDATED_VS_MARKET")
    if c.calibration_method is None:
        soft.append("CALIBRATION_UNAVAILABLE")

    if hard:
        c.status = DecisionStatus.NO_BET
        reasons = hard + soft
    elif soft:
        c.status = DecisionStatus.WATCH if c.ev > 0 else DecisionStatus.NO_BET
        reasons = soft
    else:
        strong = c.ev_lower is not None and c.ev_lower > 0
        if cfg.strong_requires_positive_ev_lower and strong:
            c.status = DecisionStatus.STRONG_CANDIDATE
        else:
            c.status = DecisionStatus.CANDIDATE
            if c.ev_lower is not None and c.ev_lower <= 0:
                warnings.append("EV_LOWER_BOUND_NOT_POSITIVE")
    c.reasons, c.warnings = reasons, warnings
    return c
