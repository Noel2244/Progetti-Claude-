# Model methodology

All models implement `MatchOutcomeModel.fit(snapshot, competitions)` /
`predict(fixtures)` and only ever see a `PITSnapshot`. Disputed scores
(`score_disputed=1`, e.g. results awarded by a court) are excluded from fitting.

## Baselines (the bars every model must clear)

* **Climatology** - league H/D/A base rates over the trailing 5 years with a weak prior.
  A model that does not beat it knows nothing about the teams.
* **Market** (MODEL A) - margin-removed consensus of individual bookmakers at decision time.
  A model that does not add information beyond it is not used for betting decisions.

## Elo (MODEL B) - `models/elo.py`

* Sequential updates in match order; K=20, home advantage 65 rating points, World Football
  Elo goal-difference multiplier (1, 1.5, (11+gd)/8).
* Between seasons ratings regress 20% toward the mean of last season's teams.
* New/promoted teams start at the 20th percentile of last season's ratings; teams returning
  after an absence blend 50/50 with that prior. In a competition's first observed season all
  teams start at 1500.
* **Link to 1X2**: ordered logit `P(y<=k) = sigmoid(theta_k - beta * dr/400)` fitted on
  the *pre-match* rating differences of the last 10 years (each difference was computed
  before its match, so the link is look-ahead free). Parameter uncertainty by Laplace
  approximation (numerical Hessian) -> 5/95% intervals.
* The engine is incremental and provably equal to a from-scratch fit
  (`tests/test_temporal_leakage.py::test_elo_incremental_equals_from_scratch`).

## Poisson family (MODELS C, E) and Dixon-Coles (MODEL D) - `models/goals.py`

```
log lambda_home = mu + home + att[h] - def[a]
log lambda_away = mu +        att[a] - def[h]
```

* `poisson`: static (xi = 0) over a 3-year window. `poisson_weighted`: exponential
  time decay `w = exp(-xi * days)`, xi = 0.0019/day (Dixon & Coles' 0.0065 per half-week).
* `dixon_coles`: adds tau(x, y; rho) for 0-0, 1-0, 0-1, 1-1; rho bounded to [-0.3, 0.2].
* Ridge penalty (l2=1) for identifiability/shrinkage. Teams absent at the start of the
  window are "newcomers" and are shrunk toward a jointly-estimated newcomer prior
  (g_att, g_def) rather than toward an average team; a promoted team with no data inherits it.
* L-BFGS-B with an **analytic gradient** (checked against finite differences) and warm
  starts; refit at most every 7 days in backtests (reusing an older fit cannot leak).
* Uncertainty: Laplace approximation using the penalised Poisson Hessian (rho held fixed);
  unseen teams add the empirical between-team variance. 200 draws -> 5/95% intervals.

## Score distribution engine - `models/score_matrix.py`

Truncated at 10 goals (tail mass reported) and renormalised. Derived: 1X2, double chance,
DNB, over/under any half line, BTTS, team totals, exact scores, goal-difference
distribution, Asian handicap incl. quarter lines (half-stake settlement), AH EV.
Monte Carlo sampling with deterministic seeds.

## xG model (MODEL F)

Not built: the only legal xG source integrated (StatsBomb open data) covers too few
Serie A seasons (1986/87, 2015/16) and was published years later (not point-in-time).
Built when a legitimate multi-season xG source is available.

## Advanced ML / ensembles

Deliberately postponed (directive: only after baselines are validated and only if they
improve out-of-sample quality). The feature store (`features/team_features.py`) and the
walk-forward engine are ready for a challenger; it must pass the promotion gates.

## What the models do NOT know

No lineups, injuries, suspensions, manager changes, transfers or news. Every decision
therefore carries the warning `LINEUP_UNKNOWN`, and thresholds are conservative.
