"""Score distribution engine: P(home=i, away=j) and every market derived from it.

The matrix is truncated at ``max_goals`` and the (tiny) tail mass is reported,
then the matrix is renormalised so all derived markets are coherent.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson


def dc_tau(i: int, j: int, lh: float, la: float, rho: float) -> float:
    if i == 0 and j == 0:
        return 1.0 - lh * la * rho
    if i == 0 and j == 1:
        return 1.0 + lh * rho
    if i == 1 and j == 0:
        return 1.0 + la * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(lh: float, la: float, rho: float = 0.0, max_goals: int = 10) -> tuple[np.ndarray, float]:
    """Return (normalised matrix, truncated tail mass)."""
    if not (lh > 0 and la > 0):
        raise ValueError(f"expected goals must be positive: {lh}, {la}")
    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    if rho != 0.0:
        m[0, 0] *= dc_tau(0, 0, lh, la, rho)
        m[0, 1] *= dc_tau(0, 1, lh, la, rho)
        m[1, 0] *= dc_tau(1, 0, lh, la, rho)
        m[1, 1] *= dc_tau(1, 1, lh, la, rho)
    m = np.clip(m, 0.0, None)
    total = m.sum()
    return m / total, float(max(0.0, 1.0 - total))


@dataclass
class DerivedMarkets:
    matrix: np.ndarray

    def one_x_two(self) -> tuple[float, float, float]:
        m = self.matrix
        return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())

    def total_goals(self) -> np.ndarray:
        m = self.matrix
        n = m.shape[0]
        out = np.zeros(2 * n - 1)
        for i in range(n):
            for j in range(n):
                out[i + j] += m[i, j]
        return out

    def over(self, line: float) -> float:
        tg = self.total_goals()
        k = np.arange(len(tg))
        if abs(line * 2 - round(line * 2)) > 1e-9 or float(line).is_integer():
            raise ValueError("use half-goal lines (e.g. 2.5) for over/under")
        return float(tg[k > line].sum())

    def under(self, line: float) -> float:
        return 1.0 - self.over(line)

    def btts(self) -> float:
        return float(self.matrix[1:, 1:].sum())

    def team_over(self, side: str, line: float) -> float:
        marg = self.matrix.sum(axis=1) if side == "H" else self.matrix.sum(axis=0)
        return float(marg[np.arange(len(marg)) > line].sum())

    def exact(self, i: int, j: int) -> float:
        return float(self.matrix[i, j]) if i < self.matrix.shape[0] and j < self.matrix.shape[1] else 0.0

    def double_chance(self) -> dict[str, float]:
        h, d, a = self.one_x_two()
        return {"1X": h + d, "12": h + a, "X2": d + a}

    def draw_no_bet_home(self) -> float:
        h, d, a = self.one_x_two()
        return h / (h + a)

    def goal_diff_dist(self) -> dict[int, float]:
        m = self.matrix
        out: dict[int, float] = {}
        for i in range(m.shape[0]):
            for j in range(m.shape[1]):
                out[i - j] = out.get(i - j, 0.0) + float(m[i, j])
        return out

    def asian_handicap_home(self, line: float) -> dict[str, float]:
        """Win/push/loss probabilities for the home side at a handicap ``line``.

        Quarter lines are split into two half-stakes (e.g. -0.25 = 0.0 and -0.5).
        Returns expected fractions: {"win","half_win","push","half_loss","loss"}.
        """
        quarter = abs(round(line * 4)) % 2 == 1
        halves = (line - 0.25, line + 0.25) if quarter else (line, line)
        out = {"win": 0.0, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 0.0}
        for gd, p in self.goal_diff_dist().items():
            r = [self._settle(gd + h) for h in halves]   # +1 win, 0 push, -1 loss for each half stake
            s = r[0] + r[1]
            key = {2: "win", 1: "half_win", 0: "push", -1: "half_loss", -2: "loss"}[s]
            out[key] += p
        return out

    @staticmethod
    def _settle(adjusted_margin: float) -> int:
        if adjusted_margin > 1e-9:
            return 1
        if adjusted_margin < -1e-9:
            return -1
        return 0

    def asian_handicap_ev(self, line: float, odds: float) -> float:
        """Expected profit per unit staked on the home side at decimal ``odds``."""
        o = self.asian_handicap_home(line)
        return (o["win"] * (odds - 1) + o["half_win"] * (odds - 1) / 2
                - o["half_loss"] / 2 - o["loss"])

    def all_markets(self) -> dict[str, float]:
        h, d, a = self.one_x_two()
        out = {"1X2:H": h, "1X2:D": d, "1X2:A": a, "BTTS:YES": self.btts(), "BTTS:NO": 1 - self.btts()}
        for line in (0.5, 1.5, 2.5, 3.5, 4.5):
            out[f"OU{line}:OVER"] = self.over(line)
            out[f"OU{line}:UNDER"] = self.under(line)
        return out

    def expected_goals(self) -> tuple[float, float]:
        g = np.arange(self.matrix.shape[0])
        return float((self.matrix.sum(axis=1) * g).sum()), float((self.matrix.sum(axis=0) * g).sum())


BATCH_MARKETS = ("H", "D", "A", "OVER25", "BTTS")


def one_x_two_batch(lh: np.ndarray, la: np.ndarray, rho: float = 0.0, max_goals: int = 10) -> np.ndarray:
    """Vectorised 1X2 for many (lambda_home, lambda_away) pairs -> array (n, 3) [H, D, A]."""
    return markets_batch(lh, la, rho, max_goals)[:, :3]


def markets_batch(lh: np.ndarray, la: np.ndarray, rho: float = 0.0, max_goals: int = 10) -> np.ndarray:
    """Vectorised markets for many (lambda_home, lambda_away) pairs -> (n, 5) [H, D, A, OVER25, BTTS]."""
    g = np.arange(max_goals + 1)
    # uncertainty draws can wander into absurd territory; keep expected goals in a football range
    lh = np.clip(np.asarray(lh, float), 0.02, 6.0)
    la = np.clip(np.asarray(la, float), 0.02, 6.0)
    ph = poisson.pmf(g[None, :], lh[:, None])
    pa = poisson.pmf(g[None, :], la[:, None])
    m = ph[:, :, None] * pa[:, None, :]
    if rho != 0.0:
        m[:, 0, 0] *= 1.0 - lh * la * rho
        m[:, 0, 1] *= 1.0 + lh * rho
        m[:, 1, 0] *= 1.0 + la * rho
        m[:, 1, 1] *= 1.0 - rho
        m = np.clip(m, 0.0, None)
    m /= m.sum(axis=(1, 2), keepdims=True)
    size = max_goals + 1
    lower = np.tril(np.ones((size, size)), -1)
    home = (m * lower).sum(axis=(1, 2))
    draw = np.trace(m, axis1=1, axis2=2)
    tot = np.add.outer(np.arange(size), np.arange(size))
    over25 = (m * (tot > 2.5)).sum(axis=(1, 2))
    btts = m[:, 1:, 1:].sum(axis=(1, 2))
    return np.stack([home, draw, 1.0 - home - draw, over25, btts], axis=1)


def monte_carlo_scores(matrix: np.ndarray, n: int, seed: int) -> np.ndarray:
    """Sample (home, away) scores from a matrix with a deterministic seed."""
    rng = np.random.default_rng(seed)
    flat = matrix.ravel()
    idx = rng.choice(flat.size, size=n, p=flat / flat.sum())
    return np.stack(np.unravel_index(idx, matrix.shape), axis=1)
