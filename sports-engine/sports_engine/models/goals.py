"""Poisson-family goal models: static Poisson, time-weighted (dynamic) Poisson, Dixon-Coles.

log lambda_home = mu + home + att[h] - def[a]
log lambda_away = mu +        att[a] - def[h]

* exponential time decay w = exp(-xi * days_ago) (Dixon & Coles 1997); xi=0 -> static;
* Dixon-Coles low-score dependence tau(x, y; rho) for 0-0, 1-0, 0-1, 1-1;
* ridge penalty l2 for identifiability and shrinkage; teams that were NOT in the
  competition at the start of the window ("newcomers", i.e. promoted) are shrunk
  toward a jointly estimated newcomer prior (g_att, g_def) instead of toward an
  average team - a promoted team with no data inherits that prior;
* analytic gradient (L-BFGS-B); warm starts across refits;
* Laplace approximation (Poisson-part Hessian, rho fixed) for parameter
  uncertainty -> 5%/95% intervals of the 1X2 probabilities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from sports_engine.models.base import MatchOutcomeModel, MatchPrediction
from sports_engine.models.score_matrix import BATCH_MARKETS, DerivedMarkets, markets_batch, score_matrix
from sports_engine.pit.store import PITSnapshot


@dataclass
class GoalModelParams:
    xi_per_day: float = 0.0019
    window_days: int = 1095
    l2: float = 1.0
    l2_prior: float = 0.1
    max_goals: int = 10
    dixon_coles: bool = False
    newcomer_days: int = 120
    min_team_matches: int = 6
    uncertainty: bool = True
    n_draws: int = 200
    seed: int = 11
    rho_bounds: tuple[float, float] = (-0.3, 0.2)


class GoalModel(MatchOutcomeModel):
    version = "1.0"

    def __init__(self, params: GoalModelParams | None = None, name: str | None = None):
        self.params = params or GoalModelParams()
        if name:
            self.name = name
        else:
            self.name = "dixon_coles" if self.params.dixon_coles else ("poisson_weighted" if self.params.xi_per_day > 0 else "poisson")
        self.teams: list[str] = []
        self.idx: dict[str, int] = {}
        self.theta: np.ndarray | None = None
        self.cov: np.ndarray | None = None
        self.n_team_matches: dict[str, int] = {}
        self._fitted_as_of = None
        self._warm: dict[str, float] = {}
        self._spread: dict[str, float] = {}

    def params_dict(self) -> dict:
        return asdict(self.params)

    # ------------------------------------------------------------------ layout
    def _n(self) -> int:
        return len(self.teams)

    def _unpack(self, th: np.ndarray):
        n = self._n()
        mu, home = th[0], th[1]
        att = th[2:2 + n]
        de = th[2 + n:2 + 2 * n]
        g_att, g_def = th[2 + 2 * n], th[3 + 2 * n]
        rho = th[4 + 2 * n] if self.params.dixon_coles else 0.0
        return mu, home, att, de, g_att, g_def, rho

    # ------------------------------------------------------------------ objective
    def _objective(self, th, hi, ai, x, y, w, nc):
        p = self.params
        n = self._n()
        mu, home, att, de, g_att, g_def, rho = self._unpack(th)
        eh = mu + home + att[hi] - de[ai]
        ea = mu + att[ai] - de[hi]
        lam = np.exp(eh)
        mu_ = np.exp(ea)
        ll = x * eh - lam + y * ea - mu_
        dh = x - lam
        da = y - mu_
        drho = 0.0
        if p.dixon_coles:
            tau = np.ones_like(lam)
            dtau_h = np.zeros_like(lam)
            dtau_a = np.zeros_like(lam)
            dtau_r = np.zeros_like(lam)
            m00 = (x == 0) & (y == 0)
            m01 = (x == 0) & (y == 1)
            m10 = (x == 1) & (y == 0)
            m11 = (x == 1) & (y == 1)
            tau[m00] = 1 - lam[m00] * mu_[m00] * rho
            tau[m01] = 1 + lam[m01] * rho
            tau[m10] = 1 + mu_[m10] * rho
            tau[m11] = 1 - rho
            if np.any(tau <= 1e-10):
                return 1e12, np.zeros_like(th)
            dtau_r[m00] = -lam[m00] * mu_[m00]
            dtau_h[m00] = -lam[m00] * mu_[m00] * rho
            dtau_a[m00] = -lam[m00] * mu_[m00] * rho
            dtau_r[m01] = lam[m01]
            dtau_h[m01] = lam[m01] * rho
            dtau_r[m10] = mu_[m10]
            dtau_a[m10] = mu_[m10] * rho
            dtau_r[m11] = -1.0
            ll = ll + np.log(tau)
            dh = dh + dtau_h / tau
            da = da + dtau_a / tau
            drho = -float(np.sum(w * dtau_r / tau))
        f = -float(np.sum(w * ll))
        gh = -w * dh
        ga = -w * da
        ra = att - g_att * nc
        rd = de - g_def * nc
        f += 0.5 * p.l2 * float(ra @ ra + rd @ rd) + 0.5 * p.l2_prior * (g_att ** 2 + g_def ** 2)
        grad = np.zeros_like(th)
        grad[0] = gh.sum() + ga.sum()
        grad[1] = gh.sum()
        grad[2:2 + n] = np.bincount(hi, gh, n) + np.bincount(ai, ga, n) + p.l2 * ra
        grad[2 + n:2 + 2 * n] = -np.bincount(ai, gh, n) - np.bincount(hi, ga, n) + p.l2 * rd
        grad[2 + 2 * n] = -p.l2 * float(ra @ nc) + p.l2_prior * g_att
        grad[3 + 2 * n] = -p.l2 * float(rd @ nc) + p.l2_prior * g_def
        if p.dixon_coles:
            grad[4 + 2 * n] = drho
        return f, grad

    # ------------------------------------------------------------------ fit
    def fit(self, snapshot: PITSnapshot, competition_ids: list[str]) -> None:
        p = self.params
        as_of = pd.Timestamp(snapshot.as_of)
        res = snapshot.results(competition_ids, since=(as_of - pd.Timedelta(days=p.window_days)).to_pydatetime(),
                               exclude_disputed=True)
        if len(res) < 50:
            self.theta = None
            self._fitted_as_of = snapshot.as_of
            return
        dates = pd.to_datetime(res["match_date"])
        days_ago = (as_of.tz_localize(None) - dates).dt.days.clip(lower=0).to_numpy(float)
        w = np.exp(-p.xi_per_day * days_ago)
        teams = sorted(set(res["home_team_id"]) | set(res["away_team_id"]))
        self.teams = teams
        self.idx = {t: i for i, t in enumerate(teams)}
        hi = res["home_team_id"].map(self.idx).to_numpy()
        ai = res["away_team_id"].map(self.idx).to_numpy()
        x = res["home_goals"].to_numpy(float)
        y = res["away_goals"].to_numpy(float)
        first = pd.concat([pd.Series(dates.values, index=res["home_team_id"].values),
                           pd.Series(dates.values, index=res["away_team_id"].values)]).groupby(level=0).min()
        window_start = dates.min()
        nc = np.array([1.0 if (first[t] - window_start).days > p.newcomer_days else 0.0 for t in teams])
        counts = pd.concat([res["home_team_id"], res["away_team_id"]]).value_counts()
        self.n_team_matches = {t: int(counts.get(t, 0)) for t in teams}
        n = len(teams)
        size = 4 + 2 * n + (1 if p.dixon_coles else 0)
        th0 = np.zeros(size)
        th0[0] = np.log(max(0.3, (x.mean() + y.mean()) / 2))
        th0[1] = 0.25
        for t, i in self.idx.items():
            th0[2 + i] = self._warm.get(f"att:{t}", 0.0)
            th0[2 + n + i] = self._warm.get(f"def:{t}", 0.0)
        for k, j in (("mu", 0), ("home", 1), ("g_att", 2 + 2 * n), ("g_def", 3 + 2 * n)):
            if k in self._warm:
                th0[j] = self._warm[k]
        bounds = [(None, None)] * size
        if p.dixon_coles:
            th0[-1] = self._warm.get("rho", -0.05)
            bounds[-1] = p.rho_bounds
        sol = minimize(self._objective, th0, args=(hi, ai, x, y, w, nc), jac=True, method="L-BFGS-B",
                       bounds=bounds, options={"maxiter": 500})
        self.theta = sol.x
        self._nc = nc
        mu, home, att, de, g_att, g_def, rho = self._unpack(self.theta)
        self._warm = {"mu": mu, "home": home, "g_att": g_att, "g_def": g_def, "rho": rho}
        self._warm.update({f"att:{t}": att[i] for t, i in self.idx.items()})
        self._warm.update({f"def:{t}": de[i] for t, i in self.idx.items()})
        self.cov = self._laplace(hi, ai, w) if p.uncertainty else None
        established = [i for t, i in self.idx.items() if self.n_team_matches[t] >= p.min_team_matches]
        self._spread = {"att": float(np.var(att[established])) if len(established) > 2 else 0.1,
                        "def": float(np.var(de[established])) if len(established) > 2 else 0.1}
        self._fitted_as_of = snapshot.as_of

    def _laplace(self, hi, ai, w) -> np.ndarray | None:
        """Inverse Hessian of the penalised Poisson objective (rho held fixed)."""
        p = self.params
        n = self._n()
        size = 4 + 2 * n
        mu, home, att, de, g_att, g_def, rho = self._unpack(self.theta)
        lam = np.exp(mu + home + att[hi] - de[ai])
        mu_ = np.exp(mu + att[ai] - de[hi])
        m = len(hi)
        xh = np.zeros((m, size))
        xa = np.zeros((m, size))
        r = np.arange(m)
        xh[:, 0] = 1; xh[:, 1] = 1; xh[r, 2 + hi] = 1; xh[r, 2 + n + ai] = -1
        xa[:, 0] = 1; xa[r, 2 + ai] = 1; xa[r, 2 + n + hi] = -1
        h = (xh * (w * lam)[:, None]).T @ xh + (xa * (w * mu_)[:, None]).T @ xa
        nc = self._nc
        for i in range(n):
            h[2 + i, 2 + i] += p.l2
            h[2 + n + i, 2 + n + i] += p.l2
            h[2 + i, 2 + 2 * n] -= p.l2 * nc[i]
            h[2 + 2 * n, 2 + i] -= p.l2 * nc[i]
            h[2 + n + i, 3 + 2 * n] -= p.l2 * nc[i]
            h[3 + 2 * n, 2 + n + i] -= p.l2 * nc[i]
        h[2 + 2 * n, 2 + 2 * n] += p.l2 * float(nc @ nc) + p.l2_prior
        h[3 + 2 * n, 3 + 2 * n] += p.l2 * float(nc @ nc) + p.l2_prior
        try:
            cov = np.linalg.inv(h)
        except np.linalg.LinAlgError:
            return None
        cov = (cov + cov.T) / 2
        return cov if np.all(np.linalg.eigvalsh(cov) > -1e-12) else None

    # ------------------------------------------------------------------ predict
    def _team_vec(self, team: str, side: str) -> tuple[np.ndarray, float]:
        """Linear-combination row (over theta without rho) for att/def of ``team``."""
        n = self._n()
        v = np.zeros(4 + 2 * n)
        extra_var = 0.0
        if team in self.idx:
            v[(2 if side == "att" else 2 + n) + self.idx[team]] = 1.0
        else:  # unseen (promoted) team -> newcomer prior + empirical between-team spread
            v[2 + 2 * n if side == "att" else 3 + 2 * n] = 1.0
            extra_var = self._spread.get(side, 0.1)
        return v, extra_var

    def expected_goals(self, home: str, away: str) -> tuple[float, float, np.ndarray, np.ndarray, float]:
        n = self._n()
        size = 4 + 2 * n
        base = np.zeros(size)
        att_h, vh1 = self._team_vec(home, "att")
        def_a, vh2 = self._team_vec(away, "def")
        att_a, va1 = self._team_vec(away, "att")
        def_h, va2 = self._team_vec(home, "def")
        row_h = base.copy(); row_h[0] = 1; row_h[1] = 1; row_h += att_h - def_a
        row_a = base.copy(); row_a[0] = 1; row_a += att_a - def_h
        th = self.theta[:size]
        return float(np.exp(row_h @ th)), float(np.exp(row_a @ th)), row_h, row_a, vh1 + vh2 + va1 + va2

    def predict(self, fixtures: pd.DataFrame) -> list[MatchPrediction]:
        if self.theta is None:
            return []
        p = self.params
        rho = self._unpack(self.theta)[6]
        rng = np.random.default_rng(p.seed)
        out = []
        for r in fixtures.itertuples(index=False):
            lh, la, row_h, row_a, extra = self.expected_goals(r.home_team_id, r.away_team_id)
            m, tail = score_matrix(lh, la, rho, p.max_goals)
            h, d, a = DerivedMarkets(m).one_x_two()
            interval = sd = None
            if self.cov is not None:
                var_h = float(row_h @ self.cov @ row_h) + extra / 2
                var_a = float(row_a @ self.cov @ row_a) + extra / 2
                cv = float(row_h @ self.cov @ row_a)
                cov2 = np.array([[var_h, cv], [cv, var_a]])
                eta = rng.multivariate_normal([np.log(lh), np.log(la)], cov2, size=p.n_draws, check_valid="ignore")
                sims = markets_batch(np.exp(eta[:, 0]), np.exp(eta[:, 1]), rho, p.max_goals)
                lo, hi_ = np.percentile(sims, [5, 95], axis=0)
                interval = {k: (float(lo[i]), float(hi_[i])) for i, k in enumerate(BATCH_MARKETS)}
                sd = {k: float(sims[:, i].std()) for i, k in enumerate(BATCH_MARKETS)}
            notes = []
            for t in (r.home_team_id, r.away_team_id):
                if t not in self.idx:
                    notes.append(f"{t}: no matches in window - newcomer prior used")
            pred = MatchPrediction(
                match_id=r.match_id, model=self.name, model_version=self.version,
                p_home=h, p_draw=d, p_away=a, lambda_home=lh, lambda_away=la, rho=float(rho), matrix=m,
                interval=interval, sd=sd,
                home_matches=self.n_team_matches.get(r.home_team_id, 0),
                away_matches=self.n_team_matches.get(r.away_team_id, 0),
                notes=notes + ([f"truncated tail mass {tail:.2e}"] if tail > 1e-6 else []),
            )
            pred.validate()
            out.append(pred)
        return out

    def team_strengths(self) -> pd.DataFrame:
        if self.theta is None:
            return pd.DataFrame()
        mu, home, att, de, g_att, g_def, rho = self._unpack(self.theta)
        return pd.DataFrame({"team_id": self.teams, "attack": att, "defence": de,
                             "matches_in_window": [self.n_team_matches[t] for t in self.teams]}).sort_values(
            "attack", ascending=False)


def poisson_model(**kw) -> GoalModel:
    return GoalModel(GoalModelParams(xi_per_day=0.0, dixon_coles=False, **kw), name="poisson")


def weighted_poisson_model(**kw) -> GoalModel:
    kw.setdefault("xi_per_day", 0.0019)
    return GoalModel(GoalModelParams(dixon_coles=False, **kw), name="poisson_weighted")


def dixon_coles_model(**kw) -> GoalModel:
    kw.setdefault("xi_per_day", 0.0019)
    return GoalModel(GoalModelParams(dixon_coles=True, **kw), name="dixon_coles")
