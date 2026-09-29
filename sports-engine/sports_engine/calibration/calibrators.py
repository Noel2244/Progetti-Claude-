"""Multiclass probability calibrators and a conservative selection rule.

* identity       - no change (the default unless another method *proves* better)
* temperature    - p_k ∝ p_k^(1/T)  (1 parameter)
* dirichlet      - multinomial logistic regression on log p with L2 (Kull et al. 2019)
* ovr_isotonic   - one-vs-rest isotonic regression, renormalised
* ovr_platt      - one-vs-rest logistic on logit(p), renormalised

Calibrators are fitted on *past out-of-sample* predictions only; see the
walk-forward backtest for how this is enforced.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.special import logit, softmax
from sklearn.isotonic import IsotonicRegression

from sports_engine.calibration.metrics import log_loss

EPS = 1e-6
# Floor for the output of every fitted (non-identity) calibrator. Isotonic step functions can emit
# ~0 probabilities at the edge of their training range; in the Serie A backtest one such output
# (1e-6 for outcomes that then happened) turned a 0.969 log-loss season into 1.030.
PROB_FLOOR = 0.01


def _clip(P: np.ndarray) -> np.ndarray:
    P = np.clip(np.asarray(P, float), EPS, 1.0)
    return P / P.sum(axis=1, keepdims=True)


def _floor(Q: np.ndarray, floor: float = PROB_FLOOR) -> np.ndarray:
    """Exact probability floor: entries below ``floor`` are pinned at it and only the others are
    rescaled (water-filling), so the result is >= floor everywhere and still sums to 1."""
    Q = np.clip(np.asarray(Q, float), 0.0, None)
    Q = Q / Q.sum(axis=1, keepdims=True)
    out = Q.copy()
    for _ in range(Q.shape[1]):
        pinned = out < floor
        free_mass = 1.0 - floor * pinned.sum(axis=1, keepdims=True)
        free_sum = np.where(pinned, 0.0, Q).sum(axis=1, keepdims=True)
        out = np.where(pinned, floor, Q * free_mass / np.where(free_sum > 0, free_sum, 1.0))
        if not (out < floor - 1e-12).any():
            break
    return out


class Calibrator:
    name = "base"

    def fit(self, P, y) -> "Calibrator":
        return self

    def transform(self, P) -> np.ndarray:
        raise NotImplementedError

    def params(self) -> dict:
        return {}


class IdentityCalibrator(Calibrator):
    name = "identity"

    def transform(self, P):
        return _clip(P)


class TemperatureScaling(Calibrator):
    name = "temperature"

    def __init__(self):
        self.T = 1.0

    def fit(self, P, y):
        L = np.log(_clip(P))
        y = np.asarray(y, int)

        def nll(t):
            Q = softmax(L / np.exp(t[0]), axis=1)
            return -np.mean(np.log(np.clip(Q[np.arange(len(y)), y], 1e-15, 1)))

        res = minimize(nll, np.array([0.0]), method="L-BFGS-B", bounds=[(-2, 2)])
        self.T = float(np.exp(res.x[0]))
        return self

    def transform(self, P):
        return _floor(softmax(np.log(_clip(P)) / self.T, axis=1))

    def params(self):
        return {"T": self.T}


class DirichletCalibrator(Calibrator):
    name = "dirichlet"

    def __init__(self, l2: float = 1e-2):
        self.l2 = l2
        self.W = None
        self.b = None

    def fit(self, P, y):
        L = np.log(_clip(P))
        y = np.asarray(y, int)
        k = L.shape[1]
        onehot = np.eye(k)[y]
        n = len(y)

        def f(th):
            W = th[: k * k].reshape(k, k)
            b = th[k * k:]
            Z = L @ W.T + b
            Q = softmax(Z, axis=1)
            nll = -np.mean(np.sum(onehot * np.log(np.clip(Q, 1e-15, 1)), axis=1))
            Wd = W - np.eye(k)   # shrink toward identity mapping
            pen = 0.5 * self.l2 * (np.sum(Wd ** 2) + np.sum(b ** 2))
            G = (Q - onehot) / n
            gW = G.T @ L + self.l2 * Wd
            gb = G.sum(axis=0) + self.l2 * b
            return nll + pen, np.concatenate([gW.ravel(), gb])

        th0 = np.concatenate([np.eye(k).ravel(), np.zeros(k)])
        res = minimize(f, th0, jac=True, method="L-BFGS-B")
        self.W = res.x[: k * k].reshape(k, k)
        self.b = res.x[k * k:]
        return self

    def transform(self, P):
        return _floor(softmax(np.log(_clip(P)) @ self.W.T + self.b, axis=1))

    def params(self):
        return {"W": self.W.round(4).tolist(), "b": self.b.round(4).tolist()}


class OvRIsotonic(Calibrator):
    name = "ovr_isotonic"

    def __init__(self):
        self.models = []

    def fit(self, P, y):
        P = _clip(P)
        y = np.asarray(y, int)
        self.models = [IsotonicRegression(y_min=EPS, y_max=1 - EPS, out_of_bounds="clip").fit(P[:, k], (y == k).astype(float))
                       for k in range(P.shape[1])]
        return self

    def transform(self, P):
        P = _clip(P)
        Q = np.column_stack([m.predict(P[:, k]) for k, m in enumerate(self.models)])
        return _floor(Q)


class OvRPlatt(Calibrator):
    name = "ovr_platt"

    def __init__(self):
        self.ab = []

    def fit(self, P, y):
        from sports_engine.calibration.metrics import calibration_slope_intercept
        P = _clip(P)
        y = np.asarray(y, int)
        self.ab = [calibration_slope_intercept(P[:, k], (y == k).astype(float)) for k in range(P.shape[1])]
        return self

    def transform(self, P):
        from scipy.special import expit
        P = _clip(P)
        Q = np.column_stack([expit(a + b * logit(P[:, k])) for k, (b, a) in enumerate(self.ab)])
        return _floor(Q)


CALIBRATORS = {c.name: c for c in (IdentityCalibrator, TemperatureScaling, DirichletCalibrator, OvRIsotonic, OvRPlatt)}


@dataclass
class CalibrationChoice:
    method: str
    calibrator: Calibrator
    validation: dict = field(default_factory=dict)
    reason: str = ""


def select_calibrator(P_train, y_train, P_val, y_val, candidates=("identity", "temperature", "dirichlet", "ovr_isotonic"),
                      min_improvement: float = 0.0005, min_train: int = 600, require_significance: bool = True,
                      n_boot: int = 500, seed: int = 0) -> CalibrationChoice:
    """Pick a calibrator on a *later* validation block.

    ``identity`` wins unless another method improves validation log loss by at least
    ``min_improvement`` AND (when ``require_significance``) the paired-bootstrap 95% CI of
    the per-prediction improvement excludes zero. A fixed threshold alone proved too
    permissive: on synthetic data with a correctly specified model it still selected
    calibrators that made later seasons worse.
    """
    from sports_engine.calibration.metrics import log_loss_per_obs, paired_bootstrap
    y_val = np.asarray(y_val, int)
    base_obs = log_loss_per_obs(_clip(P_val), y_val)
    base = float(base_obs.mean())
    scores = {"identity": base}
    if len(y_train) < min_train:
        return CalibrationChoice("identity", IdentityCalibrator(), scores, f"too few training predictions ({len(y_train)})")
    fitted, per_obs = {}, {}
    for name in candidates:
        if name == "identity":
            continue
        try:
            c = CALIBRATORS[name]().fit(P_train, y_train)
            obs = log_loss_per_obs(c.transform(P_val), y_val)
            scores[name] = float(obs.mean())
            fitted[name], per_obs[name] = c, obs
        except Exception:  # a failing calibrator is simply not selected
            scores[name] = float("nan")
    best = min((k for k in scores if k != "identity" and np.isfinite(scores[k])), key=lambda k: scores[k], default=None)
    if best is None or scores[best] >= base - min_improvement:
        return CalibrationChoice("identity", IdentityCalibrator(), scores, "no calibrator beat identity by the required margin")
    if require_significance:
        bs = paired_bootstrap(per_obs[best], base_obs, n_boot=n_boot, seed=seed)
        scores["_bootstrap_ci"] = [bs["ci_low"], bs["ci_high"]]
        if bs["ci_high"] >= 0:
            return CalibrationChoice("identity", IdentityCalibrator(), scores,
                                     f"{best} improvement {base - scores[best]:.4f} not significant (CI [{bs['ci_low']:+.4f}, {bs['ci_high']:+.4f}])")
    return CalibrationChoice(best, fitted[best], scores, f"improves validation log loss by {base - scores[best]:.4f} (significant)")


# --------------------------------------------------------------------------- persistence
# JSON only (never pickle): stored artefacts must not be able to execute code.

def calibrator_to_dict(c: Calibrator) -> dict:
    if isinstance(c, IdentityCalibrator):
        return {"method": "identity"}
    if isinstance(c, TemperatureScaling):
        return {"method": "temperature", "T": c.T}
    if isinstance(c, DirichletCalibrator):
        return {"method": "dirichlet", "W": c.W.tolist(), "b": c.b.tolist(), "l2": c.l2}
    if isinstance(c, OvRPlatt):
        return {"method": "ovr_platt", "ab": [list(x) for x in c.ab]}
    if isinstance(c, OvRIsotonic):
        return {"method": "ovr_isotonic",
                "curves": [{"x": m.X_thresholds_.tolist(), "y": m.y_thresholds_.tolist()} for m in c.models]}
    raise TypeError(f"cannot serialise {type(c).__name__}")


class _InterpIsotonic:
    """Frozen isotonic curve (piecewise-linear interpolation, clipped at the ends)."""

    def __init__(self, x, y):
        self.x = np.asarray(x, float)
        self.y = np.asarray(y, float)

    def predict(self, p):
        return np.interp(p, self.x, self.y)


def calibrator_from_dict(d: dict) -> Calibrator:
    m = d["method"]
    if m == "identity":
        return IdentityCalibrator()
    if m == "temperature":
        c = TemperatureScaling()
        c.T = float(d["T"])
        return c
    if m == "dirichlet":
        c = DirichletCalibrator(d.get("l2", 1e-2))
        c.W, c.b = np.asarray(d["W"], float), np.asarray(d["b"], float)
        return c
    if m == "ovr_platt":
        c = OvRPlatt()
        c.ab = [tuple(x) for x in d["ab"]]
        return c
    if m == "ovr_isotonic":
        c = OvRIsotonic()
        c.models = [_InterpIsotonic(cv["x"], cv["y"]) for cv in d["curves"]]
        return c
    raise ValueError(f"unknown calibrator {m!r}")
