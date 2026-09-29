"""Probability-quality metrics.

Multiclass inputs: ``P`` shape (n, K) with rows summing to 1, ``y`` integer class
indices. For 1X2 the class order is (H, D, A), which is also the natural order
for the Ranked Probability Score.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit

EPS = 1e-15


def _check(P: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    P = np.asarray(P, dtype=float)
    y = np.asarray(y, dtype=int)
    if P.ndim != 2 or len(P) != len(y):
        raise ValueError("P must be (n, K) and y length n")
    return P, y


def log_loss(P, y) -> float:
    P, y = _check(P, y)
    return float(-np.mean(np.log(np.clip(P[np.arange(len(y)), y], EPS, 1.0))))


def log_loss_per_obs(P, y) -> np.ndarray:
    P, y = _check(P, y)
    return -np.log(np.clip(P[np.arange(len(y)), y], EPS, 1.0))


def brier(P, y) -> float:
    return float(np.mean(brier_per_obs(P, y)))


def brier_per_obs(P, y) -> np.ndarray:
    P, y = _check(P, y)
    onehot = np.eye(P.shape[1])[y]
    return np.sum((P - onehot) ** 2, axis=1)


def rps(P, y) -> float:
    return float(np.mean(rps_per_obs(P, y)))


def rps_per_obs(P, y) -> np.ndarray:
    P, y = _check(P, y)
    k = P.shape[1]
    onehot = np.eye(k)[y]
    cp = np.cumsum(P, axis=1)[:, :-1]
    co = np.cumsum(onehot, axis=1)[:, :-1]
    return np.sum((cp - co) ** 2, axis=1) / (k - 1)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return float(max(0.0, centre - half)), float(min(1.0, centre + half))


def reliability_table(p: np.ndarray, outcome: np.ndarray, n_bins: int = 10, strategy: str = "quantile") -> list[dict]:
    """Binary reliability diagram data with Wilson 95% intervals per bin."""
    p = np.asarray(p, float)
    o = np.asarray(outcome, float)
    if strategy == "quantile":
        edges = np.unique(np.quantile(p, np.linspace(0, 1, n_bins + 1)))
    else:
        edges = np.linspace(0, 1, n_bins + 1)
    if len(edges) < 2:
        edges = np.array([0.0, 1.0])
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
    rows = []
    for b in range(len(edges) - 1):
        m = idx == b
        n = int(m.sum())
        if n == 0:
            continue
        k = int(o[m].sum())
        lo, hi = wilson_interval(k, n)
        rows.append({"bin": b, "lower": float(edges[b]), "upper": float(edges[b + 1]), "n": n,
                     "mean_predicted": float(p[m].mean()), "observed": k / n, "ci_low": lo, "ci_high": hi})
    return rows


def ece(p: np.ndarray, outcome: np.ndarray, n_bins: int = 10, strategy: str = "quantile") -> float:
    rows = reliability_table(p, outcome, n_bins, strategy)
    n = sum(r["n"] for r in rows)
    return float(sum(r["n"] * abs(r["mean_predicted"] - r["observed"]) for r in rows) / max(1, n))


def calibration_slope_intercept(p: np.ndarray, outcome: np.ndarray) -> tuple[float, float]:
    """Logistic recalibration  logit P(y=1) = a + b * logit(p). Perfect: a=0, b=1.

    Unpenalised maximum likelihood (not sklearn's default L2 penalty).
    """
    x = logit(np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6))
    y = np.asarray(outcome, float)

    def nll(th):
        z = th[0] + th[1] * x
        return float(np.sum(np.logaddexp(0, z) - y * z))

    def grad(th):
        r = expit(th[0] + th[1] * x) - y
        return np.array([r.sum(), (r * x).sum()])

    res = minimize(nll, np.array([0.0, 1.0]), jac=grad, method="BFGS")
    return float(res.x[1]), float(res.x[0])


def multiclass_report(P, y, labels=("H", "D", "A"), n_bins: int = 10) -> dict:
    P, y = _check(P, y)
    out = {"n": int(len(y)), "log_loss": log_loss(P, y), "brier": brier(P, y), "rps": rps(P, y), "classes": {}}
    if P.shape[1] == 3:
        pass
    else:
        out.pop("rps")
    for k, lab in enumerate(labels):
        pk, ok = P[:, k], (y == k).astype(float)
        slope, intercept = calibration_slope_intercept(pk, ok)
        out["classes"][lab] = {
            "mean_predicted": float(pk.mean()), "observed_rate": float(ok.mean()),
            "ece": ece(pk, ok, n_bins), "slope": slope, "intercept": intercept,
            "reliability": reliability_table(pk, ok, n_bins),
        }
    out["ece_mean"] = float(np.mean([c["ece"] for c in out["classes"].values()]))
    return out


def paired_bootstrap(a: np.ndarray, b: np.ndarray, n_boot: int = 2000, seed: int = 0,
                     blocks: np.ndarray | None = None) -> dict:
    """Bootstrap CI of mean(a - b) (per-observation losses). Block bootstrap if ``blocks`` given."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = a - b
    rng = np.random.default_rng(seed)
    if blocks is None:
        idx = rng.integers(0, len(d), size=(n_boot, len(d)))
        means = d[idx].mean(axis=1)
    else:
        ub = np.unique(blocks)
        groups = [np.where(blocks == g)[0] for g in ub]
        sums = np.array([d[g].sum() for g in groups])
        counts = np.array([len(g) for g in groups])
        pick = rng.integers(0, len(groups), size=(n_boot, len(groups)))
        means = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean_diff": float(d.mean()), "ci_low": float(lo), "ci_high": float(hi),
            "p_a_better": float((means < 0).mean()), "n": int(len(d)), "n_boot": n_boot}
