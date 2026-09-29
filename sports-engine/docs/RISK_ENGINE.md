# Risk engine (staking, limits, bankroll)

## Staking (`decision/staking.py`)

* Default **conservative**: fractional Kelly with fraction 0.25, on the market-shrunk
  probability, capped at 2% of bankroll per selection. `fixed` (1%) also available.
* **Martingale, doubling after losses, Fibonacci, D'Alembert, Labouchere, loss chasing are
  refused** (`ForbiddenStakingError`). Structurally: `stake_fraction(p, odds, cfg)` has no
  access to past results, so progressions are impossible (a test asserts the signature).
* Zero stake whenever EV at the conservative probability is not positive.

## Limits (`config.yaml: risk`)

MAX_SINGLE_EXPOSURE 2%, MAX_DAILY_EXPOSURE 10%, MAX_MATCH_EXPOSURE 3%,
MAX_CORRELATED_EXPOSURE 4% (same match), MAX_TEAM_EXPOSURE 5%, MAX_LEAGUE_EXPOSURE 8%/day,
MAX_LEGS 5. `apply_risk_limits` allocates greedily by conservative EV and records which
limit capped each stake.

## Bankroll simulation (`portfolio/simulation.py`)

Monte Carlo of repeated periods with fixed-fraction staking; each path draws its "true"
probabilities inside the prediction intervals (model error propagated). Outputs final
bankroll quantiles, probability of loss, **risk of ruin** (bankroll below 50%), median and
95th-percentile **max drawdown**, volatility, exposure, and the model's expected log growth.
A test demonstrates that over-staking (25% per bet) raises risk of ruin sharply.

## Paper bankroll

`paper status` reports paper bets, P/L in units (1 unit = 1% of starting bankroll), CLV and
the implied bankroll. Nothing is ever executed: the system has no bookmaker integration.

## Portfolio optimisation

Mean-variance / robust optimisation is intentionally not implemented yet: with no validated
edge, optimisation would only "manufacture attractive-looking results". The greedy
limit-respecting allocator is the justified minimum.
