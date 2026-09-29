from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from sports_engine.api.app import create_app
from sports_engine.correlation.slips import Leg, evaluate_slip
from sports_engine.models.score_matrix import DerivedMarkets, score_matrix
from sports_engine.paper.engine import PaperEngine
from sports_engine.pipeline.runner import PipelineRunner
from sports_engine.portfolio.simulation import BetSpec, simulate_bankroll
from sports_engine.research_lab.simulate import simulate_league

from .test_paper_and_registry import load_synthetic


def test_same_match_correlation_is_exact():
    m, _ = score_matrix(1.8, 0.9, -0.05)
    dm = DerivedMarkets(m)
    ph, po = dm.one_x_two()[0], dm.over(2.5)
    legs = [Leg("m1", "1X2", "H", 1.7, ph, 1.8, 0.9, -0.05), Leg("m1", "OU", "OVER", 2.0, po, 1.8, 0.9, -0.05, 2.5)]
    ev = evaluate_slip(legs, n_sims=200_000)
    assert ev.adjusted_probability > ev.naive_probability          # home win and overs are positively correlated
    assert ev.adjusted_probability == pytest.approx(ev.monte_carlo_probability, abs=4 * ev.monte_carlo_se + 1e-3)
    assert "SAME_MATCH_CORRELATION:m1" in ev.flags


def test_mutually_exclusive_and_independence_flags():
    m, _ = score_matrix(1.4, 1.1)
    h, d, a = DerivedMarkets(m).one_x_two()
    ev = evaluate_slip([Leg("m1", "1X2", "H", 2.0, h, 1.4, 1.1), Leg("m1", "1X2", "A", 3.5, a, 1.4, 1.1)], n_sims=10_000)
    assert ev.adjusted_probability == 0 and any(f.startswith("MUTUALLY_EXCLUSIVE") for f in ev.flags)
    ev2 = evaluate_slip([Leg("m1", "1X2", "H", 2.0, h, 1.4, 1.1), Leg("m2", "1X2", "H", 2.0, h, 1.4, 1.1)], n_sims=10_000)
    assert "INDEPENDENCE_ASSUMED_ACROSS_MATCHES" in ev2.flags
    assert ev2.adjusted_probability == pytest.approx(h * h)
    with pytest.raises(ValueError):
        evaluate_slip([Leg(f"m{i}", "1X2", "H", 2.0, h, 1.4, 1.1) for i in range(6)], max_legs=5)


def test_correlation_can_remove_apparent_edge():
    m, _ = score_matrix(1.2, 1.2)
    dm = DerivedMarkets(m)
    ph, pu = dm.one_x_two()[0], dm.under(2.5)
    # prices that look +EV when legs are (wrongly) treated as independent
    odds_h, odds_u = 1.05 / ph, 1.05 / pu
    ev = evaluate_slip([Leg("m", "1X2", "H", odds_h, ph, 1.2, 1.2), Leg("m", "OU", "UNDER", odds_u, pu, 1.2, 1.2, 0, 2.5)],
                       n_sims=20_000)
    assert ev.ev_naive > 0 and ev.ev_adjusted < 0
    assert "EDGE_DISAPPEARS_AFTER_CORRELATION_ADJUSTMENT" in ev.flags


def test_bankroll_simulation():
    r = simulate_bankroll([BetSpec(0.5, 2.1, 0.02, 0.45, 0.55)] * 3, periods=100, n_paths=2000, seed=1)
    assert 0 <= r["risk_of_ruin"] <= 1 and 0 <= r["median_max_drawdown"] <= 1
    heavy = simulate_bankroll([BetSpec(0.5, 2.0, 0.25)], periods=100, n_paths=2000, seed=1)
    assert heavy["risk_of_ruin"] > r["risk_of_ruin"]          # over-staking is visibly dangerous


def test_pipeline_runner_isolates_failures(db):
    run = PipelineRunner(db)
    run.run("ok", lambda: {"x": 1})
    bad = run.run("bad", lambda: 1 / 0, retries=1, backoff=0.0)
    dep = run.run("needs_bad", lambda: 1, requires=["bad"])
    after = run.run("independent", lambda: "fine")
    assert bad.status == "FAILED" and bad.attempts == 2
    assert dep.status == "SKIPPED" and after.status == "OK"
    assert not run.summary()["ok"]
    again = run.run("ok", lambda: {"x": 2})
    assert again.status == "SKIPPED"            # checkpoint: completed tasks are not re-run


@pytest.fixture()
def client(settings, db):
    m, o, _ = simulate_league(n_teams=10, seasons=3, start_year=2019, seed=9, market="efficient")
    load_synthetic(db, m, o)
    s = settings.with_overrides({"paper": {"horizon_days": 10}})
    PaperEngine(s, db).run(now=datetime(2021, 11, 3, 12, tzinfo=timezone.utc))
    return TestClient(create_app(s, db)), db


def test_api_endpoints(client):
    c, db = client
    assert c.get("/health").json()["paper_chain_ok"] is True
    assert c.get("/").status_code == 200
    rows = c.get("/value?include_no_bet=true").json()
    assert rows and all(r["reasons"] is not None for r in rows)
    mid = rows[0]["match_id"]
    d = c.get(f"/matches/{mid}").json()
    assert d["score_matrix"]["labels"] == ["0", "1", "2", "3+"]
    grid = d["score_matrix"]["home_rows_away_cols"]
    assert abs(sum(map(sum, grid)) - 1) < 1e-3
    for ep in ("/matches", "/predictions", "/models", "/backtests", "/experiments", "/bankroll", "/clv", "/data-health",
               "/model-health", "/historical-data", "/coverage", "/research-lab"):
        assert c.get(ep).status_code == 200, ep
    assert c.get("/matches/../../etc").status_code in (400, 404)
    assert c.get("/matches/bad id").status_code == 400
    ids = db.query("SELECT prediction_id FROM paper_prediction WHERE market='1X2' AND odds IS NOT NULL LIMIT 2")
    if len(ids) == 2:
        r = c.get("/slips", params={"ids": ",".join(x["prediction_id"] for x in ids)})
        assert r.status_code == 200 and "adjusted_probability" in r.json()


def test_api_write_requires_token(settings, db, monkeypatch):
    monkeypatch.setenv("SPORTS_ENGINE_API_TOKEN", "s3cret-token")
    c = TestClient(create_app(settings, db))
    assert c.post("/journal", params={"note": "x"}).status_code == 401
    assert c.post("/journal", params={"note": "x"}, headers={"X-API-Token": "s3cret-token"}).status_code == 200
