"""Bookmaker margin (overround) removal.

Given decimal odds o_i for a complete set of mutually exclusive outcomes, the raw
implied probabilities pi_i = 1/o_i sum to 1 + margin. Methods:

* multiplicative (basic normalisation):  p_i = pi_i / sum(pi)
* additive:                              p_i = pi_i - margin / n   (can go negative -> rejected)
* power:                                 p_i = pi_i ** k,  sum p_i = 1
* shin (1992/1993):                      insider-trading model; solves for z
* odds_ratio (Cheung 2015):              p_i = pi_i / (c + pi_i - c * pi_i), sum p_i = 1

Power, Shin and odds-ratio correct the favourite-longshot bias better than
multiplicative normalisation; see docs/MARKET_ENGINE.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

METHODS = ("multiplicative", "additive", "power", "shin", "odds_ratio")


@dataclass
class FairProbabilities:
    fair: np.ndarray
    raw: np.ndarray
    margin: float
    method: str
    param: float | None = None

    def as_dict(self, labels) -> dict:
        return {"method": self.method, "margin": self.margin, "param": self.param,
                "raw": dict(zip(labels, self.raw.round(6).tolist())),
                "fair": dict(zip(labels, self.fair.round(6).tolist()))}


def implied(odds) -> np.ndarray:
    o = np.asarray(odds, dtype=float)
    if o.ndim != 1 or len(o) < 2:
        raise ValueError("need odds for at least two outcomes")
    if np.any(~np.isfinite(o)) or np.any(o <= 1.0):
        raise ValueError(f"decimal odds must be > 1: {o}")
    return 1.0 / o


def remove_margin(odds, method: str = "power") -> FairProbabilities:
    pi = implied(odds)
    s = float(pi.sum())
    margin = s - 1.0
    n = len(pi)
    if method == "multiplicative":
        return FairProbabilities(pi / s, pi, margin, method)
    if method == "additive":
        p = pi - margin / n
        if np.any(p <= 0):
            raise ValueError("additive method produced non-positive probability")
        return FairProbabilities(p / p.sum(), pi, margin, method)
    if margin <= 1e-12:
        # no (or negative) margin: nothing to remove beyond normalisation
        return FairProbabilities(pi / s, pi, margin, method, None)
    if method == "power":
        f = lambda k: float(np.sum(pi ** k) - 1.0)
        k = brentq(f, 1.0, 50.0)
        p = pi ** k
        return FairProbabilities(p / p.sum(), pi, margin, method, k)
    if method == "shin":
        def shin_p(z: float) -> np.ndarray:
            return (np.sqrt(z * z + 4.0 * (1.0 - z) * pi * pi / s) - z) / (2.0 * (1.0 - z))
        f = lambda z: float(shin_p(z).sum() - 1.0)
        z = brentq(f, 0.0, 0.999) if f(0.0) > 0 else 0.0
        p = shin_p(z)
        return FairProbabilities(p / p.sum(), pi, margin, method, z)
    if method == "odds_ratio":
        def orp(c: float) -> np.ndarray:
            return pi / (c + pi - c * pi)
        f = lambda c: float(orp(c).sum() - 1.0)
        c = brentq(f, 1.0, 100.0)
        p = orp(c)
        return FairProbabilities(p / p.sum(), pi, margin, method, c)
    raise ValueError(f"unknown method {method!r}; choose from {METHODS}")
