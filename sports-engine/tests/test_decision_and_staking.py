from __future__ import annotations

import pytest

from sports_engine.core.enums import DecisionStatus
from sports_engine.core.errors import ForbiddenStakingError
from sports_engine.decision.engine import Candidate, DecisionConfig, decide, expected_value
from sports_engine.decision.staking import (
    RiskLimits,
    StakingConfig,
    apply_risk_limits,
    kelly_fraction,
    stake_fraction,
)


def cand(**kw):
    base = dict(match_id="m", market="1X2", selection="H", line=None, model="dc", model_prob=0.55, raw_model_prob=0.55,
                prob_low=0.50, prob_high=0.60, market_fair_prob=0.48, market_raw_prob=0.5, odds=2.0, bookmaker="b",
                data_quality=0.9, agreement_diff=0.03, home_matches=40, away_matches=40, calibration_method="identity")
    base.update(kw)
    return Candidate(**base)


def test_ev_formula():
    assert expected_value(0.5, 2.2) == pytest.approx(0.1)
    assert expected_value(0.5, 2.0) == pytest.approx(0.0)


def test_strong_candidate_when_everything_passes():
    c = decide(cand(prob_low=0.52), DecisionConfig())
    assert c.status == DecisionStatus.STRONG_CANDIDATE
    assert c.edge == pytest.approx(0.07) and c.ev == pytest.approx(0.10)
    c = decide(cand(prob_low=0.50), DecisionConfig())      # EV at the lower bound is exactly 0 -> not "strong"
    assert c.status == DecisionStatus.CANDIDATE and "EV_LOWER_BOUND_NOT_POSITIVE" in c.warnings


def test_no_odds_is_insufficient_data():
    c = decide(cand(odds=None, market_fair_prob=None), DecisionConfig())
    assert c.status == DecisionStatus.INSUFFICIENT_DATA and "NO_MARKET_ODDS" in c.reasons


def test_edge_consumed_by_margin():
    # beats the fair probability but not the actual price
    c = decide(cand(model_prob=0.49, raw_model_prob=0.49, prob_low=0.45, market_fair_prob=0.47, odds=2.0), DecisionConfig())
    assert c.status == DecisionStatus.NO_BET
    assert "EDGE_CONSUMED_BY_MARGIN" in c.reasons


def test_edge_removed_by_calibration():
    c = decide(cand(model_prob=0.48, raw_model_prob=0.56, prob_low=0.44, market_fair_prob=0.47, odds=2.0), DecisionConfig())
    assert "EDGE_REMOVED_BY_CALIBRATION" in c.reasons


def test_model_disagreement_and_stale_block():
    c = decide(cand(agreement_diff=0.15), DecisionConfig())
    assert c.status == DecisionStatus.NO_BET and "MODEL_DISAGREEMENT" in c.reasons
    c = decide(cand(market_flags=["STALE_ODDS"]), DecisionConfig())
    assert c.status == DecisionStatus.NO_BET and "STALE_ODDS" in c.reasons


def test_insufficient_history_and_low_quality():
    assert decide(cand(home_matches=2), DecisionConfig()).status == DecisionStatus.INSUFFICIENT_DATA
    assert decide(cand(data_quality=0.3), DecisionConfig()).status == DecisionStatus.INSUFFICIENT_DATA


def test_watch_when_edge_small_but_positive():
    c = decide(cand(model_prob=0.51, raw_model_prob=0.51, prob_low=0.47, market_fair_prob=0.50, odds=2.0), DecisionConfig())
    assert c.status == DecisionStatus.WATCH
    assert "EDGE_BELOW_THRESHOLD" in c.reasons


def test_every_no_bet_has_reasons():
    for kw in ({"odds": 1.1}, {"model_prob": 0.3, "raw_model_prob": 0.3, "prob_low": 0.25}, {"agreement_diff": 0.5}):
        c = decide(cand(**kw), DecisionConfig())
        assert c.status in (DecisionStatus.NO_BET, DecisionStatus.WATCH, DecisionStatus.INSUFFICIENT_DATA)
        assert c.reasons


@pytest.mark.parametrize("name", ["martingale", "Martingale", "double_after_loss", "fibonacci", "labouchere", "loss_chasing"])
def test_forbidden_staking(name):
    with pytest.raises(ForbiddenStakingError):
        StakingConfig(method=name)


def test_kelly_and_caps():
    assert kelly_fraction(0.5, 2.0) == 0.0
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.2)
    cfg = StakingConfig(method="fractional_kelly", kelly_fraction=0.25, max_stake_fraction=0.02)
    assert stake_fraction(0.6, 2.0, cfg) == pytest.approx(0.02)          # 0.05 capped at 0.02
    assert stake_fraction(0.45, 2.0, cfg) == 0.0                         # negative EV -> no stake
    assert stake_fraction(0.6, 2.0, StakingConfig(method="fixed", unit_fraction=0.01)) == 0.01


def test_stake_is_history_independent():
    """Same inputs -> same stake, whatever happened before (no loss chasing possible)."""
    cfg = StakingConfig()
    stakes = {stake_fraction(0.58, 1.95, cfg) for _ in range(10)}
    assert len(stakes) == 1
    import inspect
    params = inspect.signature(stake_fraction).parameters
    assert set(params) == {"p_conservative", "odds", "cfg"}


def test_risk_limits():
    sels = [{"match_id": f"m{i}", "day": "2024-01-01", "league": "ITA1", "home_team": f"h{i}", "away_team": f"a{i}",
             "stake_fraction": 0.02, "ev_conservative": 0.1 - i * 0.01} for i in range(8)]
    out = apply_risk_limits(sels, RiskLimits(max_daily_exposure=0.10, max_league_exposure=0.08))
    assert sum(s["stake_fraction"] for s in out) == pytest.approx(0.08)
    same_match = [{"match_id": "m", "day": "d", "league": "L", "home_team": "h", "away_team": "a",
                   "stake_fraction": 0.02, "ev_conservative": 0.1}] * 3
    out = apply_risk_limits(same_match, RiskLimits(max_match_exposure=0.03, max_correlated_exposure=0.03))
    assert sum(s["stake_fraction"] for s in out) == pytest.approx(0.03)
