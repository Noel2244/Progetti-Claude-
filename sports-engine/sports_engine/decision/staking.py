"""Staking and risk limits.

Supported: fixed unit, fractional Kelly, capped fractional Kelly with an
uncertainty penalty (Kelly is computed on the *conservative* probability, i.e.
shrunk toward the market, never on the raw model probability).

Stakes are a pure function of (probability, odds, bankroll, config). They do NOT
depend on previous results - which makes Martingale, doubling after losses and
loss-chasing structurally impossible. Requests for such schemes are refused.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sports_engine.core.errors import ForbiddenStakingError

FORBIDDEN = {"martingale", "reverse_martingale", "fibonacci", "dalembert", "d'alembert", "labouchere",
             "double_after_loss", "loss_chasing", "chase"}


@dataclass
class StakingConfig:
    method: str = "fractional_kelly"
    unit_fraction: float = 0.01
    kelly_fraction: float = 0.25
    max_stake_fraction: float = 0.02

    def __post_init__(self):
        if self.method.lower() in FORBIDDEN or any(f in self.method.lower() for f in ("martingale", "chase", "double")):
            raise ForbiddenStakingError(f"staking method {self.method!r} is forbidden (loss-chasing / progression)")
        if self.method not in ("fixed", "fractional_kelly"):
            raise ValueError(f"unknown staking method {self.method!r}")
        if not (0 < self.kelly_fraction <= 1) or not (0 < self.max_stake_fraction <= 0.1):
            raise ValueError("kelly_fraction must be in (0,1] and max_stake_fraction in (0, 0.1]")

    @classmethod
    def from_settings(cls, settings) -> "StakingConfig":
        d = settings.get("staking", {}) or {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def kelly_fraction(p: float, odds: float) -> float:
    b = odds - 1.0
    return max(0.0, (p * b - (1.0 - p)) / b) if b > 0 else 0.0


def stake_fraction(p_conservative: float, odds: float, cfg: StakingConfig) -> float:
    """Fraction of the *current* bankroll to stake. History-independent by design."""
    if p_conservative is None or odds is None or p_conservative * odds - 1.0 <= 0:
        return 0.0
    if cfg.method == "fixed":
        f = cfg.unit_fraction
    else:
        f = cfg.kelly_fraction * kelly_fraction(p_conservative, odds)
    return float(min(f, cfg.max_stake_fraction))


@dataclass
class RiskLimits:
    max_single_exposure: float = 0.02
    max_daily_exposure: float = 0.10
    max_match_exposure: float = 0.03
    max_team_exposure: float = 0.05
    max_league_exposure: float = 0.08
    max_correlated_exposure: float = 0.04
    max_slip_legs: int = 5

    @classmethod
    def from_settings(cls, settings) -> "RiskLimits":
        d = settings.get("risk", {}) or {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def apply_risk_limits(selections: list[dict], limits: RiskLimits) -> list[dict]:
    """Greedy allocation by conservative EV; trims stakes to respect every limit.

    Each selection dict needs: match_id, day, league, home_team, away_team, stake_fraction, ev_conservative.
    Same-match selections count as correlated exposure. Returns new dicts with
    'stake_fraction' possibly reduced and 'risk_notes'.
    """
    used = defaultdict(float)
    out = []
    for s in sorted(selections, key=lambda x: -(x.get("ev_conservative") or 0.0)):
        want = min(s["stake_fraction"], limits.max_single_exposure)
        caps = {
            "daily": limits.max_daily_exposure - used[("day", s["day"])],
            "match": limits.max_match_exposure - used[("match", s["match_id"])],
            "correlated": limits.max_correlated_exposure - used[("corr", s["match_id"])],
            "home_team": limits.max_team_exposure - used[("team", s["home_team"])],
            "away_team": limits.max_team_exposure - used[("team", s["away_team"])],
            "league": limits.max_league_exposure - used[("league", s["day"], s["league"])],
        }
        allowed = max(0.0, min([want] + list(caps.values())))
        notes = [f"capped by {k}" for k, v in caps.items() if v < want]
        s2 = dict(s, stake_fraction=allowed, risk_notes=notes)
        if allowed > 0:
            used[("day", s["day"])] += allowed
            used[("match", s["match_id"])] += allowed
            used[("corr", s["match_id"])] += allowed
            used[("team", s["home_team"])] += allowed
            used[("team", s["away_team"])] += allowed
            used[("league", s["day"], s["league"])] += allowed
        out.append(s2)
    return out
