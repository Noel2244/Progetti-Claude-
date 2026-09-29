"""Bankroll Monte Carlo: drawdown distribution, risk of ruin, volatility, recovery.

Simulates repeated betting periods with a *fixed* staking rule (fractions of the
current bankroll). Probabilities are drawn from each bet's uncertainty interval
when given, so model error is propagated instead of assuming the model is exact.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class BetSpec:
    prob: float
    odds: float
    stake_fraction: float
    prob_low: float | None = None
    prob_high: float | None = None


def simulate_bankroll(bets: list[BetSpec], periods: int = 200, n_paths: int = 5000, seed: int = 11,
                      ruin_level: float = 0.5) -> dict:
    """Each period places every bet in ``bets`` once (independent outcomes)."""
    if not bets:
        return {"paths": 0}
    rng = np.random.default_rng(seed)
    k = len(bets)
    p0 = np.array([b.prob for b in bets])
    lo = np.array([b.prob_low if b.prob_low is not None else b.prob for b in bets])
    hi = np.array([b.prob_high if b.prob_high is not None else b.prob for b in bets])
    odds = np.array([b.odds for b in bets])
    f = np.array([b.stake_fraction for b in bets])
    # true probability per path ~ uniform within the interval (model uncertainty), fixed over the path
    p_true = lo + (hi - lo) * rng.uniform(size=(n_paths, k))
    bank = np.ones(n_paths)
    peak = np.ones(n_paths)
    max_dd = np.zeros(n_paths)
    ruined = np.zeros(n_paths, bool)
    log_returns = []
    for _ in range(periods):
        win = rng.uniform(size=(n_paths, k)) < p_true
        ret = np.where(win, f * (odds - 1), -f).sum(axis=1)
        new = bank * (1 + ret)
        log_returns.append(np.log(np.clip(new / bank, 1e-12, None)))
        bank = new
        peak = np.maximum(peak, bank)
        max_dd = np.maximum(max_dd, 1 - bank / peak)
        ruined |= bank < ruin_level
    lr = np.array(log_returns)
    return {
        "paths": n_paths, "periods": periods, "bets_per_period": k,
        # sum over bets of E[log growth] at the model probability (bets treated separately)
        "expected_log_growth_per_period_model": float(np.sum(p0 * np.log1p(f * (odds - 1)) + (1 - p0) * np.log1p(-f))),
        "median_final_bankroll": float(np.median(bank)),
        "p5_final_bankroll": float(np.percentile(bank, 5)),
        "p95_final_bankroll": float(np.percentile(bank, 95)),
        "prob_loss": float((bank < 1).mean()),
        "risk_of_ruin": float(ruined.mean()), "ruin_level": ruin_level,
        "median_max_drawdown": float(np.median(max_dd)), "p95_max_drawdown": float(np.percentile(max_dd, 95)),
        "volatility_per_period": float(lr.std()),
        "total_exposure_per_period": float(f.sum()),
    }
