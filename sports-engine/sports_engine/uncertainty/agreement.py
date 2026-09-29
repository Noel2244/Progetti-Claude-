"""Model agreement and combined uncertainty.

* agreement: pairwise max |p_i - p_j| and Jensen-Shannon divergence among the
  *statistical* models (the market is compared separately - disagreement with
  the market is the edge itself, not model uncertainty);
* combined interval for the primary model's probability of a selection:
  half-width = 1.645 * sqrt(sd_param^2 + sd_models^2)
  where sd_param comes from the model's own parameter uncertainty (Laplace)
  and sd_models is the spread across statistical models.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def js_divergence(p: np.ndarray, q: np.ndarray) -> float:
    p = np.clip(np.asarray(p, float), 1e-12, 1)
    q = np.clip(np.asarray(q, float), 1e-12, 1)
    m = 0.5 * (p + q)
    return float(0.5 * np.sum(p * np.log(p / m)) + 0.5 * np.sum(q * np.log(q / m)))


@dataclass
class Agreement:
    n_models: int
    max_abs_diff: float        # over all selections and model pairs
    per_selection_sd: np.ndarray
    mean_js: float
    level: str                 # HIGH | MODERATE | LOW | N/A


def model_agreement(prob_vectors: dict[str, np.ndarray], moderate: float = 0.05, low: float = 0.08) -> Agreement:
    vecs = [np.asarray(v, float) for v in prob_vectors.values()]
    if len(vecs) < 2:
        k = len(vecs[0]) if vecs else 3
        return Agreement(len(vecs), 0.0, np.zeros(k), 0.0, "N/A")
    M = np.vstack(vecs)
    diff = float(np.max(M.max(axis=0) - M.min(axis=0)))
    mean = M.mean(axis=0)
    js = float(np.mean([js_divergence(v, mean) for v in vecs]))
    level = "HIGH" if diff <= moderate else ("MODERATE" if diff <= low else "LOW")
    return Agreement(len(vecs), diff, M.std(axis=0), js, level)


def combined_interval(p: float, sd_param: float | None, sd_models: float | None, z: float = 1.645) -> tuple[float, float, float]:
    """Return (low, high, total_sd)."""
    def clean(v):
        return 0.0 if v is None or not np.isfinite(v) else float(v)
    total = float(np.sqrt(clean(sd_param) ** 2 + clean(sd_models) ** 2))
    return max(0.0, p - z * total), min(1.0, p + z * total), total
