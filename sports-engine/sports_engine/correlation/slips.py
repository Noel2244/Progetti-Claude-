"""Slip (accumulator) probability engine with correlation handling.

* legs on the SAME match: the joint probability is computed exactly from the
  match's score matrix (e.g. Home + Over 2.5 are positively correlated, so the
  naive product understates the joint probability; Home + BTTS No interacts too);
* legs on DIFFERENT matches: independence is assumed - and explicitly flagged -
  (goal-model outcomes of different matches share no latent state in this engine);
* a deterministic Monte Carlo simulation over score matrices cross-checks the
  analytic value and yields its standard error.

The engine never "manufactures" a combo: it reports naive vs adjusted probability,
EV, concentration and exposure so the user can see when an apparent edge
disappears after correlation adjustment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sports_engine.models.score_matrix import score_matrix


@dataclass
class Leg:
    match_id: str
    market: str            # 1X2 | OU | BTTS
    selection: str         # H/D/A | OVER/UNDER | YES/NO
    odds: float
    prob: float            # model probability of this leg alone
    lambda_home: float
    lambda_away: float
    rho: float = 0.0
    line: float | None = None
    home_team: str | None = None
    away_team: str | None = None
    league: str | None = None


def event_mask(market: str, selection: str, line: float | None, size: int) -> np.ndarray:
    i = np.arange(size)[:, None]
    j = np.arange(size)[None, :]
    if market == "1X2":
        return {"H": i > j, "D": i == j, "A": i < j}[selection] * np.ones((size, size), bool)
    if market == "OU":
        tot = i + j
        return (tot > line) if selection == "OVER" else (tot < line)
    if market == "BTTS":
        both = (i > 0) & (j > 0)
        return both if selection == "YES" else ~both
    raise ValueError(f"unsupported market {market}")


@dataclass
class SlipEvaluation:
    legs: int
    combined_odds: float
    naive_probability: float
    adjusted_probability: float
    ev_naive: float
    ev_adjusted: float
    monte_carlo_probability: float
    monte_carlo_se: float
    flags: list[str] = field(default_factory=list)
    concentration: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def evaluate_slip(legs: list[Leg], n_sims: int = 100_000, seed: int = 7, max_goals: int = 10, max_legs: int = 5) -> SlipEvaluation:
    if not legs:
        raise ValueError("empty slip")
    if len(legs) > max_legs:
        raise ValueError(f"slip exceeds MAX_LEGS={max_legs}")
    flags: list[str] = []
    by_match: dict[str, list[Leg]] = {}
    for leg in legs:
        by_match.setdefault(leg.match_id, []).append(leg)
    size = max_goals + 1
    adjusted = 1.0
    matrices = {}
    for mid, ls in by_match.items():
        m, _ = score_matrix(ls[0].lambda_home, ls[0].lambda_away, ls[0].rho, max_goals)
        matrices[mid] = m
        mask = np.ones((size, size), bool)
        for leg in ls:
            mask &= event_mask(leg.market, leg.selection, leg.line, size)
        p_joint = float(m[mask].sum())
        if len(ls) > 1:
            flags.append(f"SAME_MATCH_CORRELATION:{mid}")
            if p_joint == 0:
                flags.append(f"MUTUALLY_EXCLUSIVE_LEGS:{mid}")
        adjusted *= p_joint
    if len(by_match) > 1:
        flags.append("INDEPENDENCE_ASSUMED_ACROSS_MATCHES")
    naive = float(np.prod([leg.prob for leg in legs]))
    combined = float(np.prod([leg.odds for leg in legs]))
    # Monte Carlo over the same matrices
    rng = np.random.default_rng(seed)
    all_win = np.ones(n_sims, bool)
    for mid, ls in by_match.items():
        m = matrices[mid]
        idx = rng.choice(m.size, size=n_sims, p=m.ravel() / m.sum())
        hi, ai = np.unravel_index(idx, m.shape)
        for leg in ls:
            all_win &= event_mask(leg.market, leg.selection, leg.line, size)[hi, ai]
    p_mc = float(all_win.mean())
    se = float(np.sqrt(max(p_mc * (1 - p_mc), 1e-12) / n_sims))
    teams = [t for leg in legs for t in (leg.home_team, leg.away_team) if t]
    conc = {
        "same_match_legs": max(len(v) for v in by_match.values()),
        "distinct_matches": len(by_match),
        "max_team_repeats": max([teams.count(t) for t in set(teams)], default=0),
        "leagues": sorted({leg.league for leg in legs if leg.league}),
        "markets": sorted({leg.market for leg in legs}),
    }
    ev_naive = naive * combined - 1.0
    ev_adj = adjusted * combined - 1.0
    if ev_naive > 0 >= ev_adj:
        flags.append("EDGE_DISAPPEARS_AFTER_CORRELATION_ADJUSTMENT")
    return SlipEvaluation(len(legs), combined, naive, adjusted, ev_naive, ev_adj, p_mc, se, flags, conc)
