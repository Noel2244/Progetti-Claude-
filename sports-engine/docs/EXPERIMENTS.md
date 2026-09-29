# Experiments

Registry: `experiment` table (`experiments/registry.py`).

Every backtest writes one immutable record: family (research question), name, hypothesis,
dataset fingerprint, feature version, code version (git commit, `-dirty` if uncommitted),
model list, hyper-parameters, seed, training / validation / test periods, whether the
holdout was used, **number of candidate configurations**, metrics, notes and a content hash
over all stored fields (`experiments verify` recomputes it). UPDATE/DELETE are blocked by
triggers; corrections are new versions with `parent_id`.

## Multiple-testing protection

`family_stats()` sums candidate configurations per family and reports the Bonferroni alpha
and a warning such as: *"36 configurations tested in this family: at alpha=0.05 about 1.8
false 'discoveries' are expected by chance. Demand confirmation on untouched data."*
Backtest reports embed this. When research on a family becomes excessive, define a new
holdout period.

## Holdout protection

`holdout.start_date` in `config.yaml`. Backtests clip at the holdout unless explicitly
asked with a written reason; every access is logged (append-only). Two or more accesses to
the same holdout mark it contaminated in the report.

## Abort rules (Research Lab)

Discard an experiment that uses future data, lacks sample size (< 1,000 OOS predictions for
promotion), improves only one short period, worsens calibration materially, fails
robustness (majority of seasons), depends on fragile features, or needs prohibited data.

## Commands

```
python -m sports_engine experiments           # stats, recent runs, integrity check
python -m sports_engine gates --run-id <id> --model dixon_coles --reference elo
python -m sports_engine gates --run-id <id> --model dixon_coles --reference elo --promote
python -m sports_engine nested --model dixon_coles --param xi_per_day=0,0.001,0.0019,0.003 --outer 2015-2024
```
