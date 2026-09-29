# Research Lab

```
IDEA -> EXPERIMENT -> WALK-FORWARD -> CALIBRATION -> MARKET BENCHMARK -> ROBUSTNESS
     -> CHALLENGER -> PROMOTION (gates) -> LIVE PAPER EVIDENCE
```

## Tools available now

* **Walk-forward engine** with pluggable model factories (`models/registry.py`,
  `run_backtest(..., overrides=...)` for parameter variants, `family=` for accounting).
* **Synthetic truth** (`research_lab/simulate.py`, `python -m sports_engine simulate`):
  a league with known team strengths and bookmakers that are either efficient or biased
  (e.g. overpricing home favourites). The engine must find *no* robust edge in the
  efficient scenario and must detect the bias (with positive fair CLV) in the biased one.
* **Promotion gates** (`models/champion.py`): no leakage (suite is run), adequate sample,
  OOS, calibration (ECE <= 0.03, slopes 0.8-1.25), beats reference with CI, robustness
  (better in >= 60% of seasons), market benchmark, reproducibility (clean git tree +
  dataset fingerprint). Two scopes: *probability champion* (serves probabilities) and
  *betting eligible* (additionally requires the market benchmark).
* **Experiment registry** with multiple-testing accounting and a guarded holdout.

## First experiments to run (in order)

1. Enable football-data (owner, private use) -> re-run Serie A with the **market
   benchmark** and CLV. The only question that matters for betting: does any model add
   information beyond the market?
2. Nested hyper-parameter search for xi (time decay), l2, Elo K/home advantage - inner
   loop strictly on seasons before each outer test season; count every candidate.
3. Decay structure: exponential vs rolling window vs season weights vs regime-based.
4. Calibration methods by probability region (draws are notoriously miscalibrated).
5. Ensemble (average / stacking of Elo + DC + market) - only if it beats the best single
   model with a CI excluding zero across seasons.
6. Feature challengers (rest days, congestion, promoted flag) in a regularised multinomial
   logit - must beat DC on log loss out-of-sample.

## Rules

No promotion on ROI. No repeated looks at the final holdout. Simpler models stay as
baselines forever. A result that holds in one season only is noise until proven otherwise.
