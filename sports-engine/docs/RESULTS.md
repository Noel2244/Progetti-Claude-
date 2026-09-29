# Results

Every number below comes from a report in `reports/backtests/` (see the run id) or from a
command output; nothing is typed from memory. Paper mode, research only.

## 1. Serie A walk-forward, 1995/96 - 2024/25 (real data, no odds)

Run **`bt_6b33d98e2f07d2aa`** - code `abe78dba3774` (clean tree), dataset fingerprint
`15f94fcc1a17ce21`, experiment `exp_52c0ca49e37ba653`. 10,733 out-of-sample matches (one disputed
result excluded), 3-season calibration burn-in from 1992/93, final holdout (from
2025-07-01) untouched. Decision times: 6,174 matches at 00:00 local on match day (date-only
seasons), 4,560 at kickoff - 60 min (seasons with exact kickoff times).

| model | log loss | Brier | RPS | mean ECE | calib. slope H / D / A |
|---|---:|---:|---:|---:|---|
| climatology (league base rates) | 1.0646 | 0.6432 | 0.2222 | 0.0125 | 0.82 / 0.53 / 0.93 |
| Poisson (static) | 0.9911 | 0.5916 | 0.1968 | 0.0236 | 1.00 / 0.81 / 1.06 |
| Poisson (time-weighted) | 0.9869 | 0.5889 | 0.1955 | 0.0216 | 1.02 / 0.79 / 1.08 |
| Dixon-Coles | 0.9846 | 0.5877 | 0.1953 | 0.0169 | 1.01 / 0.86 / 1.06 |
| **Elo** | **0.9818** | **0.5863** | **0.1948** | 0.0177 | 0.96 / 0.75 / 1.02 |

(served = sequentially calibrated probabilities; calibration was kept at identity in 30-33
of 33 seasons per model.)

Paired comparisons (block bootstrap by week, 95% CI; negative = first model better):

| comparison | mean diff | 95% CI | verdict |
|---|---:|---|---|
| Elo vs climatology | -0.0829 | [-0.0899, -0.0748] | Elo clearly better |
| Dixon-Coles vs climatology | -0.0801 | [-0.0868, -0.0730] | clearly better |
| Dixon-Coles vs Elo | +0.0028 | [-0.0006, +0.0061] | **not distinguishable** (Elo better in 20 of 30 seasons) |
| weighted Poisson vs Elo | +0.0052 | [+0.0013, +0.0088] | Elo significantly better |
| static Poisson vs Elo | +0.0094 | [+0.0051, +0.0132] | Elo significantly better |

### What this says (and does not say)

* **FACT**: team-strength models carry real information: ~0.08 log loss better than base rates,
  consistently in every one of the 30 seasons.
* **Complexity has not earned its place.** Dixon-Coles is not better than a well-linked Elo;
  time decay matters (weighted > static Poisson). This is exactly the "simpler models remain
  competitive" warning of the directive.
* **Draws are the weak spot of every model.** The Poisson family under-predicts draws
  (mean predicted 24.4-26.2% vs observed 27.4%) and over-predicts away wins (28.9-29.6% vs
  27.3%); Dixon-Coles' rho narrows the gap. Elo gets the draw *rate* right (28.0%) but
  discriminates draws poorly (slope 0.75 < 0.8, which fails the calibration gate).
* **No betting conclusion is possible.** The data contain no bookmaker odds, so the market
  benchmark - "does the model add information beyond the market?" - is unavailable, and it
  must be *measured*, not assumed: enable football-data (owner, private use) and re-run.

### Bugs found by the real data (all fixed, all regression-tested)

| Found by | Problem | Fix |
|---|---|---|
| first real run (`bt_7102412ef0109c46`) | one-vs-rest isotonic calibration emitted 1e-6 probabilities; two such outcomes happened (log loss 13.7 each) and turned Elo's 2018/19 from 0.969 into 1.030 | exact 1% probability floor on every fitted calibrator |
| ingestion | StatsBomb kickoff times shifted +1 h in winter (216 disagreements) | StatsBomb kickoffs APPROXIMATE, demoted, conflicts recorded |
| ingestion | Verona-Roma 2020 awarded 3-0 vs 0-0 on the pitch | `score_disputed`, excluded from training/evaluation |
| ingestion | openfootball 2025-26 list-shaped scores | parser accepts both, FORMAT_DRIFT warnings |
| profiling | Arrow-string `isin` made snapshots 3x slower | index-based lookups (leakage tests re-run) |

## 2. Known-truth checks on SYNTHETIC markets (Research Lab)

`python -m sports_engine simulate --scenario efficient|biased` - 20-team league, 6 seasons,
Dixon-Coles truth, 4 bookmakers with noise and 5% margin; in *biased*, pre-match prices
overrate home favourites by 6 pp (closing prices are fair). Clearly synthetic, never mixed
with real data.

| | efficient market | biased market |
|---|---|---|
| models vs market (log loss) | market **significantly better** for all 4 models | not distinguishable |
| selections evaluated / candidates (CANDIDATE + STRONG) | 4,560 / 586 | 4,560 / 602 |
| paper bets after risk limits | 586 | 602 |
| yield (95% CI) | -2.7% [-16.7%, +11.4%] | +4.6% [-10.1%, +20.0%] |
| **mean fair CLV (95% CI)** | **-3.23% [-3.44%, -3.01%]** | **+1.03% [+0.51%, +1.54%]** |
| mean price CLV vs same book / share "beating the close" | +2.9% / 91% | +7.5% / 91% |
| hit rate vs model-expected | 32.6% vs 37.2% | 31.9% vs 35.2% |
| max drawdown (units of 1% bankroll) | 32.6 | 25.4 |

Lessons encoded in the engine:

* In an efficient market every model is reported **significantly worse than the market**:
  the system says "no information beyond the market" instead of inventing an edge.
* **ROI over hundreds of bets is still noise** (both CIs include zero); **fair CLV separates
  the two worlds**. Price CLV against the same book is misleading: line-shopping noisy
  quotes "beats the close" ~90% of the time even when the bets are bad.
* Even in the efficient market the NO BET engine let ~13% of selections through as
  candidates - the model's own errors look like edges (winner's curse: hit rate 32.6% vs
  37.2% expected). Hence the rule that live candidates require a model that has passed the
  market-benchmark gate (`MODEL_NOT_VALIDATED_VS_MARKET`).
* Two more bugs surfaced here: calibrator selection by a fixed threshold still picked
  harmful calibrators (now requires a significant bootstrap improvement), and team exposure
  limits never released after settlement (fixed; the betting simulation had been capped at
  ~42 bets instead of ~600).

## 3. Live paper predictions

Run on 2026-09-29 (`paper run --horizon 14`): the next 10 Serie A fixtures (10-11 October
2026 onward; openfootball shows no fixtures between 21 September and 9 October) x 5 selections
(1X2 + over/under 2.5) = 50 predictions, each with probability, interval, all cutoffs,
snapshot fingerprint, model/feature/calibrator versions and reasons.

* **All 50 are `INSUFFICIENT_DATA` (`NO_ODDS`)**: no market prices are available to the
  engine, and the champion is not betting-eligible (`model_validated_vs_market: false`).
  This is the correct output, not a failure.
* A second run after the final backtest wrote 50 new *versions* (the live calibrator changed);
  the 50 originals remain untouched and are referenced via `supersedes` - 100 immutable rows,
  hash chain verified (`paper verify`).
* Example (latest version): Inter v Parma - H 0.770 [0.640, 0.899], D 0.152 [0.082, 0.221],
  A 0.079 [0.016, 0.142]; Over 2.5 0.605 [0.451, 0.759]. Intervals are widest where teams
  have little recent top-flight data or the models disagree: the engine shows it instead of
  hiding it.
* League drift check (last 380 vs previous 1,900 matches): home-win rate 0.407 -> 0.395,
  draw rate 0.272 -> 0.247, goals/match 2.70 -> 2.50 - all OK at the 1% level.

## 4. Promotion gates

`python -m sports_engine gates --run-id bt_6b33d98e2f07d2aa --model <m> --reference climatology`
(runs the leakage test-suite first):

| gate | Dixon-Coles | Elo |
|---|---|---|
| no_leakage (suite executed) | PASS | PASS |
| adequate_sample (10,733 >= 1,000) | PASS | PASS |
| out_of_sample (walk-forward) | PASS | PASS |
| calibration (ECE <= 0.03, slopes 0.8-1.25) | PASS (0.0169; 1.01 / 0.86 / 1.06) | **FAIL** (draw slope 0.75) |
| beats_reference (CI excludes 0) | PASS (-0.0801) | PASS (-0.0829) |
| robustness (better in >= 60% of seasons) | PASS (100% of 30) | PASS (100% of 30) |
| market_benchmark | **FAIL - unavailable (no odds)** | **FAIL - unavailable** |
| reproducibility (clean code + dataset fingerprint) | PASS | PASS |
| **probability champion eligible** | **yes** | no |
| **betting eligible** | **no** | no |

Dixon-Coles was promoted as **probability champion** (`dixon_coles@abe78dba3774`, scope
"probability"). Because it is not betting-eligible, the live engine cannot produce
CANDIDATE statuses until a market benchmark with real odds has been passed.

Reproducibility: re-running the same configuration on the same code and data produced
bit-identical metrics (`bt_b7272a7f85bad9c4` and `bt_6b33d98e2f07d2aa`).

## 5. Run history (all kept; experiments are never deleted)

| run | code | what it is |
|---|---|---|
| `bt_7102412ef0109c46` | `d31076301368` | first reproducible run; exposed the isotonic near-zero probability bug (Elo 2018/19: 1.030) |
| `bt_b7272a7f85bad9c4` | `6ecd1443f1b6` (stamped dirty only by an untracked report) | calibrator floor fix |
| `bt_6b33d98e2f07d2aa` | `abe78dba3774` (clean) | **final** - identical metrics to the previous run |

Every run is registered in the `baseline_models` experiment family; the multiple-testing
accounting in each report counts all of them.

## 6. What to do next to answer the betting question

1. As the private owner, read football-data.co.uk's terms and enable the provider (or import
   its CSVs manually), then `validate_data` and re-run the backtest: the market benchmark,
   betting simulation and CLV sections will fill in automatically.
2. Only if a model is *not significantly worse* than the market out-of-sample, with positive
   fair CLV and stable per-season results, does it become betting-eligible - and even then
   only in paper mode, accumulating live out-of-sample evidence.
