# Correlation engine and slips

`correlation/slips.py` - `evaluate_slip(legs)` returns naive probability (product of legs),
**correlation-adjusted probability**, combined odds, naive vs adjusted EV, a Monte Carlo
estimate with standard error, flags and concentration.

## Same-match legs: exact

All legs on one match are evaluated as a single event on that match's score matrix:
`P(A and B) = sum over (i, j) of P(i, j) * 1[A](i, j) * 1[B](i, j)`.
Supported events: 1X2, over/under (any half line), BTTS. Examples:

* Home win + Over 2.5 - positively correlated: naive product *understates* the joint.
* Home win + Away win - mutually exclusive: joint 0, flagged `MUTUALLY_EXCLUSIVE_LEGS`.
* Home win + Under 2.5 - negatively correlated: a combo priced "fairly" by multiplying can be
  -EV; flagged `EDGE_DISAPPEARS_AFTER_CORRELATION_ADJUSTMENT` when naive EV > 0 >= adjusted EV.

## Cross-match legs

Assumed independent and flagged `INDEPENDENCE_ASSUMED_ACROSS_MATCHES`. Our goal models
share no latent state across matches; common shocks (weather, league-wide scoring trends)
are not modelled - a documented limitation.

## Concentration

Same-match legs, distinct matches, repeated teams, leagues and markets are reported so that
several slips that are effectively the same exposure can be spotted. MAX_LEGS (default 5) is
enforced.

## Monte Carlo slip simulator

Deterministic seed, default 100,000 simulations over the score matrices; the analytic value
and the simulation must agree within a few standard errors (tested).

API: `GET /slips?ids=<paper_prediction_id>,<...>`.
