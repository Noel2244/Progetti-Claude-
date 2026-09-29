from __future__ import annotations

import numpy as np
import pytest

from sports_engine.calibration.calibrators import (
    CALIBRATORS,
    calibrator_from_dict,
    calibrator_to_dict,
    select_calibrator,
)
from sports_engine.calibration.metrics import (
    brier,
    calibration_slope_intercept,
    ece,
    log_loss,
    paired_bootstrap,
    reliability_table,
    rps,
    wilson_interval,
)


def test_metric_known_values():
    P = np.array([[1.0, 0.0, 0.0], [0.5, 0.3, 0.2]])
    y = np.array([0, 2])
    assert brier(P, y) == pytest.approx((0 + (0.25 + 0.09 + 0.64)) / 2)
    assert log_loss(P, y) == pytest.approx((0 - np.log(0.2)) / 2, rel=1e-6)
    # RPS: perfect forecast -> 0; second: cum (0.5,0.8) vs (0,0) -> (0.25+0.64)/2
    assert rps(P, y) == pytest.approx((0 + (0.25 + 0.64) / 2) / 2)


def test_wilson():
    lo, hi = wilson_interval(50, 100)
    assert lo < 0.5 < hi and hi - lo == pytest.approx(0.19, abs=0.01)


def _sim(n=6000, distort=1.0, seed=0):
    rng = np.random.default_rng(seed)
    logits = rng.normal(0, 1.0, (n, 3))
    true = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    y = np.array([rng.choice(3, p=p) for p in true])
    shown = np.exp(logits * distort) / np.exp(logits * distort).sum(axis=1, keepdims=True)
    return true, shown, y


def test_calibrated_forecast_has_slope_one_and_low_ece():
    true, _, y = _sim()
    slope, intercept = calibration_slope_intercept(true[:, 0], (y == 0).astype(float))
    assert slope == pytest.approx(1.0, abs=0.1) and intercept == pytest.approx(0.0, abs=0.1)
    assert ece(true[:, 0], (y == 0).astype(float)) < 0.03
    rows = reliability_table(true[:, 0], (y == 0).astype(float))
    assert sum(r["n"] for r in rows) == len(y)


def test_overconfident_forecast_detected_and_fixed():
    _, shown, y = _sim(distort=2.0)
    slope, _ = calibration_slope_intercept(shown[:, 0], (y == 0).astype(float))
    assert slope < 0.8                                   # overconfidence -> slope < 1
    tr, va = slice(0, 3000), slice(3000, 6000)
    choice = select_calibrator(shown[tr], y[tr], shown[va], y[va], min_train=500)
    assert choice.method != "identity"
    assert log_loss(choice.calibrator.transform(shown[va]), y[va]) < log_loss(shown[va], y[va])


def test_identity_kept_when_already_calibrated():
    true, _, y = _sim(seed=4)
    choice = select_calibrator(true[:3000], y[:3000], true[3000:], y[3000:], min_train=500, min_improvement=0.002)
    assert choice.method == "identity"


@pytest.mark.parametrize("name", list(CALIBRATORS))
def test_calibrators_roundtrip_json(name):
    _, shown, y = _sim(n=2000, distort=1.5, seed=2)
    c = CALIBRATORS[name]().fit(shown, y)
    c2 = calibrator_from_dict(calibrator_to_dict(c))
    q1, q2 = c.transform(shown[:50]), c2.transform(shown[:50])
    assert np.allclose(q1.sum(axis=1), 1) and np.allclose(q1, q2, atol=1e-6)


def test_paired_bootstrap_detects_difference():
    rng = np.random.default_rng(1)
    a = rng.normal(0.95, 0.3, 2000)
    b = a + 0.02 + rng.normal(0, 0.05, 2000)
    r = paired_bootstrap(a, b, 500, 0)
    assert r["ci_high"] < 0 and r["p_a_better"] > 0.99
    r2 = paired_bootstrap(a, a + rng.normal(0, 0.05, 2000), 500, 0, blocks=np.arange(2000) // 10)
    assert r2["ci_low"] < 0 < r2["ci_high"]
