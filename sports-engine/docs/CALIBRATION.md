# Calibration

## Metrics (`calibration/metrics.py`)

* **Log loss** and **Brier** (multiclass), **RPS** (ranked probability score - respects the
  H > D > A ordering, standard for football).
* **ECE** per class (quantile bins) and **reliability tables** with Wilson 95% intervals.
* **Calibration slope / intercept**: unpenalised logistic regression of the outcome on
  logit(p). Perfect: slope 1, intercept 0. Slope < 1 = over-confident.
* **Paired block bootstrap** of per-match loss differences (blocks = decision weeks) for
  model-vs-model comparisons with confidence intervals.

## Calibrators (`calibration/calibrators.py`)

identity, temperature scaling, Dirichlet calibration (multinomial logistic on log p, L2
toward identity), one-vs-rest isotonic, one-vs-rest Platt. Persisted as JSON (never pickle).

## Selection rule - conservative by design

1. Calibrators are trained **only on earlier out-of-sample predictions** of the same
   walk-forward run (seasons < s), never on the season they are applied to.
2. The method is chosen on the **two most recent prior seasons** (validation), trained on
   the seasons before those; then refitted on all prior predictions.
3. `identity` wins unless another method improves validation log loss by at least
   **0.002**. Early seasons without two prior seasons stay uncalibrated.
4. The market model is never recalibrated - it is the benchmark.

Why so strict: in the synthetic efficient-market run, a looser rule (0.0005, one validation
season) selected calibrators that made out-of-sample log loss *worse*. Reports always show
raw and calibrated metrics side by side, and the interpretation says explicitly when
calibration hurt.

## Live use

`backtest` saves, per model, a calibrator selected on all out-of-sample predictions of the
run to `models/calibration/<model>.json` (with run id, dataset fingerprint, fitted period and
the validation scores). The paper engine loads it; without one, candidates carry
`CALIBRATION_UNAVAILABLE` and can be at most WATCH.

## Evaluation breakdowns

Per season (`per_season.csv`), per class, per probability bucket (reliability tables).
Per league / market / odds bucket become available as soon as those data are ingested -
the report code groups by whatever columns exist.
