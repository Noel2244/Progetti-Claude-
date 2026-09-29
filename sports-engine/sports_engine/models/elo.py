"""Elo ratings with an ordered-logit link to 1X2 probabilities.

* ratings are updated sequentially in match order using only results visible in
  the snapshot; the engine is incremental and rewinds if ``as_of`` goes back;
* goal-difference multiplier (World Football Elo style) optional;
* between seasons ratings regress toward the mean of last season's teams;
* new / promoted teams start at a low quantile of last season's ratings;
* the rating difference is mapped to P(A), P(D), P(H) by an ordered logit fitted
  on *pre-match* rating differences of past matches (no look-ahead: each
  difference was computed before that match was played);
* parameter uncertainty of the link via a Laplace approximation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

from sports_engine.models.base import MatchOutcomeModel, MatchPrediction
from sports_engine.pit.store import PITSnapshot


@dataclass
class EloParams:
    k: float = 20.0
    home_advantage: float = 65.0
    init: float = 1500.0
    season_regression: float = 0.20
    new_team_quantile: float = 0.20
    goal_diff_multiplier: bool = True
    link_window_days: int = 3650
    min_link_matches: int = 300
    scale: float = 400.0
    n_draws: int = 200
    seed: int = 7


def gd_multiplier(gd: int) -> float:
    gd = abs(gd)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11.0 + gd) / 8.0


def _ordered_logit_nll(theta: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    t0, log_gap, beta = theta
    t1 = t0 + np.exp(log_gap)
    c0 = expit(t0 - beta * x)
    c1 = expit(t1 - beta * x)
    p = np.where(y == 0, c0, np.where(y == 1, c1 - c0, 1.0 - c1))
    return -float(np.sum(np.log(np.clip(p, 1e-12, 1.0))))


def ordered_logit_probs(theta: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Return array (n, 3) with columns [home, draw, away]."""
    t0, log_gap, beta = theta
    t1 = t0 + np.exp(log_gap)
    c0 = expit(t0 - beta * x)
    c1 = expit(t1 - beta * x)
    return np.stack([1.0 - c1, c1 - c0, c0], axis=-1)


def _numerical_hessian(f, x: np.ndarray, eps: float = 1e-4) -> np.ndarray:
    n = len(x)
    h = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            e_i = np.zeros(n); e_i[i] = eps
            e_j = np.zeros(n); e_j[j] = eps
            v = (f(x + e_i + e_j) - f(x + e_i - e_j) - f(x - e_i + e_j) + f(x - e_i - e_j)) / (4 * eps * eps)
            h[i, j] = h[j, i] = v
    return h


class EloModel(MatchOutcomeModel):
    name = "elo"
    version = "1.0"

    def __init__(self, params: EloParams | None = None):
        self.params = params or EloParams()
        self._reset()

    def _reset(self) -> None:
        self.ratings: dict[str, float] = {}
        self.last_season: dict[str, int] = {}
        self.n_matches: dict[str, int] = {}
        self.season_teams: dict[int, set[str]] = {}
        self._processed_until: pd.Timestamp | None = None
        self._rec_t = np.zeros(0, dtype=np.int64)     # availability time (ns) of each processed match
        self._rec_dr = np.zeros(0)                    # pre-match rating difference
        self._rec_y = np.zeros(0, dtype=np.int8)      # 0 away, 1 draw, 2 home
        self._theta = np.array([-1.0, np.log(1.2), 1.5])
        self._cov: np.ndarray | None = None
        self._fitted_as_of = None

    def params_dict(self) -> dict:
        return asdict(self.params)

    # ------------------------------------------------------------ ratings
    def _season_mean(self, season: int) -> float:
        prev = self.season_teams.get(season - 1)
        vals = [self.ratings[t] for t in prev] if prev else list(self.ratings.values())
        return float(np.mean(vals)) if vals else self.params.init

    def _entry_rating(self, team: str, season: int) -> float:
        """Rating a team carries into ``season`` (pure function - no mutation)."""
        p = self.params
        if team in self.ratings and self.last_season.get(team, season) >= season:
            return self.ratings[team]          # fast path: already playing this season
        prev = self.season_teams.get(season - 1)
        # a promoted-team prior only exists once there is a previous season to be promoted into;
        # in a competition's first observed season every team starts at the initial rating
        promoted = float(np.quantile([self.ratings[t] for t in prev], p.new_team_quantile)) if prev else p.init
        if team not in self.ratings:
            return promoted
        r = self.ratings[team]
        last = self.last_season.get(team, season)
        mean = self._season_mean(season)
        r = r + p.season_regression * (mean - r)
        if last < season - 1:  # was absent (relegated) -> blend with the promoted-team prior
            r = 0.5 * r + 0.5 * promoted
        return r

    def _rating_for(self, team: str, season: int) -> float:
        r = self._entry_rating(team, season)
        self.ratings[team] = r
        self.last_season[team] = max(season, self.last_season.get(team, season))
        self.season_teams.setdefault(season, set()).add(team)
        return r

    def _process(self, rows: pd.DataFrame) -> None:
        p = self.params
        order = rows.sort_values(["match_date", "kickoff_utc", "match_id"], kind="mergesort", na_position="first")
        ts, drs, ys = [], [], []
        for r in order.itertuples(index=False):
            s = int(r.season_start_year)
            rh = self._rating_for(r.home_team_id, s)
            ra = self._rating_for(r.away_team_id, s)
            dr = rh + p.home_advantage - ra
            exp_h = 1.0 / (1.0 + 10.0 ** (-dr / p.scale))
            hg, ag = int(r.home_goals), int(r.away_goals)
            score = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
            y = 2 if hg > ag else (1 if hg == ag else 0)
            ts.append(pd.Timestamp(r.result_available_at).value)
            drs.append(dr)
            ys.append(y)
            k = p.k * (gd_multiplier(hg - ag) if p.goal_diff_multiplier else 1.0)
            delta = k * (score - exp_h)
            self.ratings[r.home_team_id] = rh + delta
            self.ratings[r.away_team_id] = ra - delta
            self.n_matches[r.home_team_id] = self.n_matches.get(r.home_team_id, 0) + 1
            self.n_matches[r.away_team_id] = self.n_matches.get(r.away_team_id, 0) + 1
        self._rec_t = np.concatenate([self._rec_t, np.array(ts, dtype=np.int64)])
        self._rec_dr = np.concatenate([self._rec_dr, np.array(drs, dtype=float)])
        self._rec_y = np.concatenate([self._rec_y, np.array(ys, dtype=np.int8)])

    # ------------------------------------------------------------ API
    def fit(self, snapshot: PITSnapshot, competition_ids: list[str]) -> None:
        if self._fitted_as_of is not None and snapshot.as_of < self._fitted_as_of:
            self._reset()
        res = snapshot.results(competition_ids, exclude_disputed=True)
        if self._processed_until is not None:
            res = res[res["result_available_at"] > self._processed_until]
        if len(res):
            self._process(res)
            self._processed_until = res["result_available_at"].max()
        self._fit_link(pd.Timestamp(snapshot.as_of))
        self._fitted_as_of = snapshot.as_of

    def _fit_link(self, as_of: pd.Timestamp) -> None:
        p = self.params
        lo = (as_of - pd.Timedelta(days=p.link_window_days)).value
        mask = self._rec_t > lo
        if int(mask.sum()) < p.min_link_matches:
            self._cov = None
            return
        x = self._rec_dr[mask] / p.scale
        y = self._rec_y[mask]
        f = lambda th: _ordered_logit_nll(th, x, y)
        res = minimize(f, self._theta, method="L-BFGS-B")
        if res.success or res.fun < f(self._theta):
            self._theta = res.x
        try:
            h = _numerical_hessian(f, self._theta)
            cov = np.linalg.inv(h)
            self._cov = cov if np.all(np.linalg.eigvalsh(cov) > 0) else None
        except np.linalg.LinAlgError:
            self._cov = None

    def rating(self, team: str, season: int) -> float:
        return self._entry_rating(team, season)

    def predict(self, fixtures: pd.DataFrame) -> list[MatchPrediction]:
        p = self.params
        out = []
        draws = None
        if self._cov is not None:
            rng = np.random.default_rng(p.seed)
            draws = rng.multivariate_normal(self._theta, self._cov, size=p.n_draws)
        for r in fixtures.itertuples(index=False):
            s = int(r.season_start_year)
            dr = self._entry_rating(r.home_team_id, s) + p.home_advantage - self._entry_rating(r.away_team_id, s)
            x = np.array([dr / p.scale])
            ph, pd_, pa = ordered_logit_probs(self._theta, x)[0]
            interval = sd = None
            if draws is not None:
                c0 = expit(draws[:, 0] - draws[:, 2] * x[0])
                c1 = expit(draws[:, 0] + np.exp(draws[:, 1]) - draws[:, 2] * x[0])
                sims = np.stack([1.0 - c1, c1 - c0, c0], axis=1)
                lo, hi = np.percentile(sims, [5, 95], axis=0)
                interval = {k: (float(lo[i]), float(hi[i])) for i, k in enumerate("HDA")}
                sd = {k: float(sims[:, i].std()) for i, k in enumerate("HDA")}
            pred = MatchPrediction(
                match_id=r.match_id, model=self.name, model_version=self.version,
                p_home=float(ph), p_draw=float(pd_), p_away=float(pa),
                interval=interval, sd=sd,
                home_matches=self.n_matches.get(r.home_team_id, 0), away_matches=self.n_matches.get(r.away_team_id, 0),
                notes=[f"elo_diff={dr:.1f}"] + ([] if self._cov is not None else ["link uses default parameters (insufficient history)"]),
            )
            pred.validate()
            out.append(pred)
        return out
