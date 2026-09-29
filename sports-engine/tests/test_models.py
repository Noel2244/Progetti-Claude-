from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings as hsettings
from hypothesis import strategies as st
from scipy.optimize import approx_fprime

from sports_engine.models.elo import EloModel, EloParams, gd_multiplier
from sports_engine.models.goals import GoalModel, GoalModelParams
from sports_engine.models.registry import model_factories
from sports_engine.models.score_matrix import DerivedMarkets, monte_carlo_scores, one_x_two_batch, score_matrix


def test_gd_multiplier():
    assert gd_multiplier(0) == 1.0 and gd_multiplier(1) == 1.0 and gd_multiplier(2) == 1.5
    assert gd_multiplier(3) == pytest.approx(14 / 8)


def test_elo_zero_sum_and_home_advantage(store):
    snap = store.as_of(pd.Timestamp("2020-06-01", tz="UTC").to_pydatetime())
    elo = EloModel(EloParams(season_regression=0.0))
    elo.fit(snap, ["ITA1"])
    teams = set(snap.results()["home_team_id"]) | set(snap.results()["away_team_id"])
    # promoted-team initialisation aside, updates are zero-sum: mean stays at the initial level
    assert np.mean([elo.ratings[t] for t in teams]) == pytest.approx(1500.0, abs=1e-6)
    fx = pd.DataFrame([{"match_id": "x", "home_team_id": "syn-team-00", "away_team_id": "syn-team-00", "season_start_year": 2020}])
    p = elo.predict(fx)[0]
    assert p.p_home > p.p_away          # identical teams: home advantage favours the home side


@pytest.mark.parametrize("dc", [False, True])
def test_goal_model_gradient(dc):
    rng = np.random.default_rng(0)
    m = GoalModel(GoalModelParams(dixon_coles=dc))
    n = 6
    m.teams = [f"t{i}" for i in range(n)]
    N = 200
    hi = rng.integers(0, n, N)
    ai = (hi + rng.integers(1, n, N)) % n
    x = rng.poisson(1.4, N).astype(float)
    y = rng.poisson(1.1, N).astype(float)
    w = rng.uniform(0.3, 1, N)
    nc = (rng.uniform(size=n) < 0.3).astype(float)
    th = rng.normal(0, 0.2, 4 + 2 * n + (1 if dc else 0))
    if dc:
        th[-1] = -0.05
    f = lambda t: m._objective(t, hi, ai, x, y, w, nc)[0]
    g = m._objective(th, hi, ai, x, y, w, nc)[1]
    num = approx_fprime(th, f, 1e-6)
    assert np.max(np.abs(num - g)) / max(1.0, np.max(np.abs(num))) < 1e-4


def test_goal_models_predict_valid_probabilities(store):
    snap = store.as_of(pd.Timestamp("2021-01-10", tz="UTC").to_pydatetime())
    ids = [m for m in store.fixtures()["match_id"] if m.startswith("syn_ITA1_2021")][:5]
    for name in ("poisson", "poisson_weighted", "dixon_coles"):
        model = model_factories()[name]()
        model.fit(snap, ["ITA1"])
        preds = model.predict(snap.fixtures(ids))
        assert len(preds) == 5
        for p in preds:
            p.validate()
            assert p.interval is not None and all(lo <= hi for lo, hi in p.interval.values())
            assert p.lambda_home > 0 and p.lambda_away > 0


def test_unseen_team_gets_newcomer_prior(store):
    snap = store.as_of(pd.Timestamp("2021-01-10", tz="UTC").to_pydatetime())
    model = model_factories()["dixon_coles"]()
    model.fit(snap, ["ITA1"])
    fx = pd.DataFrame([{"match_id": "new", "home_team_id": "brand-new-fc", "away_team_id": "syn-team-01", "season_start_year": 2020}])
    p = model.predict(fx)[0]
    p.validate()
    assert any("newcomer prior" in n for n in p.notes)


@hsettings(max_examples=60, deadline=None)
@given(st.floats(0.2, 4.0), st.floats(0.2, 4.0), st.floats(-0.15, 0.1))
def test_score_matrix_invariants(lh, la, rho):
    m, tail = score_matrix(lh, la, rho)
    assert m.min() >= 0 and m.sum() == pytest.approx(1.0)
    dm = DerivedMarkets(m)
    h, d, a = dm.one_x_two()
    assert h + d + a == pytest.approx(1.0)
    for line in (0.5, 1.5, 2.5, 3.5):
        assert dm.over(line) + dm.under(line) == pytest.approx(1.0)
        assert 0 <= dm.over(line) <= 1
    assert dm.over(0.5) >= dm.over(1.5) >= dm.over(2.5)
    assert 0 <= dm.btts() <= 1
    ah = dm.asian_handicap_home(-0.25)
    assert sum(ah.values()) == pytest.approx(1.0)
    b = one_x_two_batch(np.array([lh]), np.array([la]), rho)[0]
    assert np.allclose(b, [h, d, a], atol=1e-9)


def test_asian_handicap_consistency():
    m, _ = score_matrix(1.6, 1.0)
    dm = DerivedMarkets(m)
    h, d, a = dm.one_x_two()
    ah0 = dm.asian_handicap_home(0.0)                 # draw no bet
    assert ah0["win"] == pytest.approx(h) and ah0["push"] == pytest.approx(d)
    ah_q = dm.asian_handicap_home(-0.25)              # half on 0, half on -0.5
    assert ah_q["win"] == pytest.approx(h) and ah_q["half_loss"] == pytest.approx(d) and ah_q["loss"] == pytest.approx(a)
    assert dm.asian_handicap_home(-0.5)["win"] == pytest.approx(h)


def test_monte_carlo_deterministic_and_converges():
    m, _ = score_matrix(1.5, 1.1, -0.05)
    a = monte_carlo_scores(m, 100_000, seed=1)
    b = monte_carlo_scores(m, 100_000, seed=1)
    assert np.array_equal(a, b)
    ph = float((a[:, 0] > a[:, 1]).mean())
    assert ph == pytest.approx(DerivedMarkets(m).one_x_two()[0], abs=0.01)
    assert (a >= 0).all()
