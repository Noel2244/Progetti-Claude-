# Uncertainty engine

A probability is never reported alone. Each paper prediction stores:

* **estimated probability** (calibrated) and the **raw** model probability;
* **interval** `[prob_low, prob_high]`, half-width `1.645 * sqrt(sd_param^2 + sd_models^2)`:
  * `sd_param` - parameter uncertainty of the primary model (Laplace approximation of the
    penalised likelihood for goal models; of the ordered-logit link for Elo);
  * `sd_models` - dispersion across the statistical models (Elo, Poisson, weighted Poisson,
    Dixon-Coles);
* **model agreement** - max pairwise |p_i - p_j| and mean Jensen-Shannon divergence, labelled
  HIGH / MODERATE / LOW;
* **market uncertainty** - dispersion of fair probabilities across bookmakers;
* **data uncertainty** - the match-level data-quality components;
* **calibration status** - which calibrator (if any) was applied and from which run.

The market is deliberately *not* part of the model-disagreement measure: disagreement with
the market is the edge being tested, not model uncertainty.

## How uncertainty changes decisions

* `MODEL_DISAGREEMENT` (> 0.08) -> NO BET.
* EV at the market-shrunk probability `p_cons = p_mkt + 0.5 (p_model - p_mkt)` must be
  positive -> otherwise `EDGE_NOT_ROBUST_TO_UNCERTAINTY` (WATCH at best).
* STRONG_CANDIDATE additionally requires positive EV at the interval's lower bound.
* Kelly stakes use the shrunk probability, never the raw model probability.

## Known limitations

Laplace intervals ignore rho uncertainty for Dixon-Coles and rating uncertainty for Elo;
bootstrap refits would be more complete but ~200x slower. The directive's "Bayesian
posterior" option is left for the Research Lab.
