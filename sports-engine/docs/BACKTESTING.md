# Backtesting

`python -m sports_engine backtest --competitions ITA1 --start 1995-07-01 --end 2025-06-30`

## Walk-forward with point-in-time snapshots

1. **Schedule.** Every finished fixture in the window gets a decision time from
   `DecisionTimingPolicy` (see `POINT_IN_TIME_AUDIT.md`). A 3-year burn-in before the test
   window produces out-of-sample predictions used *only* to train calibrators.
2. **Batches.** Fixtures sharing a decision time form a batch; every model is fitted on
   `store.as_of(decision_time)`; Elo updates incrementally; goal models refit at most every
   7 days (reusing an older fit is always leakage-free).
3. **Sequential calibration** per season from earlier OOS predictions (see CALIBRATION.md).
4. **Evaluation** only after all predictions exist: log loss, Brier, RPS, ECE, slopes,
   per-season tables, paired block-bootstrap comparisons vs climatology, Elo and market.
5. **Betting simulation** (only if odds exist in the window): market view at each fixture's
   own decision time, NO BET engine, fractional Kelly on the market-shrunk probability,
   risk limits per day/match/team/league, P/L in units, bootstrap CI of yield, CLV
   vs closing prices (price CLV and fair CLV).

## Integrity guards

* Final holdout (`holdout.start_date`, default 2025-07-01): windows are clipped unless
  `--use-holdout --holdout-reason "..."`; every access is appended to `holdout_access`, and a
  second access triggers a "holdout contaminated - define a new one" warning.
* Every run is an immutable experiment (dataset fingerprint, code version incl. `-dirty`
  flag, config, seeds, periods, number of candidate models) - multiple testing is counted per
  family.
* Disputed scores are excluded from training and evaluation (and reported).
* Leakage tests (`tests/test_temporal_leakage.py`, `test_feature_leakage.py`,
  `test_point_in_time.py`, `test_future_information.py`) are part of the promotion gates.

## Model quality vs decision performance

Reports keep them apart: probability quality (log loss, calibration) says whether the
model is good; P/L and CLV say how decisions fared. A profitable backtest does not make a
model valid, and a losing bet does not make a model wrong.

## Outputs (`reports/backtests/<run_id>/`)

`report.md|html|json`, `predictions.csv` (every prediction with decision time, fitted-as-of
time, snapshot fingerprint, raw + calibrated probabilities, intervals), `per_season.csv`,
`bets.csv` (when odds exist: every selection with status + reasons, stake, P/L, CLV).

## Nested / purged validation

* Hyper-parameters are currently **fixed a priori** from the literature (K=20, xi=0.0019,
  l2=1, ...), so no tuning touches the test window. The calibration step is already nested
  (inner train/validation inside the past). A nested hyper-parameter search is the first
  Research-Lab experiment to add; it must use only seasons before each outer test season.
* Purging/embargo: fixtures are scored once, labels (results) become available within hours,
  and training uses only results available before the decision time. Overlapping label
  windows (the reason for purging in finance) do not arise, so no purge is applied. This is
  documented rather than silently skipped.
