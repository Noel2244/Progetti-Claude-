# Self-audit (directive section 148)

Honest status of the first build (2026-09-29). **YES** = implemented and exercised by tests or
a real run; **PARTIAL** = implemented but limited, or implemented without real data to exercise
it; **NO** = not done. The directive says the project is complete only when every answer is
YES - **it is not complete**; this is a working, validated vertical slice plus foundations.

| Question | Status | Evidence / what is missing |
|---|---|---|
| Maximised historical data acquisition? | PARTIAL | All legally usable open sources for Serie A integrated (1929-2027, 29,584 matches). The largest odds source (football-data) is opt-in and must be run by the owner (terms + robots.txt block AI agents). Other leagues: adapters/registries ready, not yet downloaded. |
| Preserved raw data? | YES | Content-addressed, read-only files; `tests/test_lake_and_download.py`. |
| Hashed datasets? | YES | sha256 per file, verified on read and by `validate-data`. |
| Recorded provenance? | YES | JSONL manifests (URL, time, ETag, license, terms) + `source_record` + `source_match.raw_sha256/raw_row`. |
| Checked licenses? | YES | `docs/LICENSES.md` (terms quoted, robots.txt checked, rejected sources with reasons). |
| Built the coverage matrix? | YES | `coverage` command, `docs/DATA_COVERAGE_MATRIX.md`. |
| Identified missing seasons / competitions / markets / timestamps? | YES | gaps report (WWII seasons, anomalous formats, no odds, date-only seasons). Competitions beyond ITA1 are listed as not yet acquired. |
| Distinguished point-in-time vs non-point-in-time data? | YES | `DataClass`, `TimestampQuality`, `pit_capability` per season. |
| Built `as_of(timestamp)`? | YES | `pit/store.py`, enforced at the data-access layer. |
| Prevented future information? | YES | snapshot filtering, fixture status from visible data only, closing odds stamped at kickoff, decision-time policy. |
| Tested temporal leakage? | YES | future-perturbation canaries for all six models, shuffled order, incremental == fresh Elo. |
| Tested feature leakage? | YES | `tests/test_feature_leakage.py`. |
| Separated historical and live data? | YES | live paper tables are separate, immutable and never used for tuning. |
| Built the market baseline? | YES | `models/baselines.MarketModel`; exercised on synthetic markets only (no real odds yet). |
| Removed market margin? | YES | 5 methods, property-tested. |
| Tracked odds history? | PARTIAL | `odds_snapshot` with timestamps + movement stats; no real odds history ingested yet. |
| Detected stale odds? | YES | `STALE_ODDS`, `OUTLIER_BEST_PRICE`, `SINGLE_BOOK` flags (tested). |
| Calculated market consensus? | YES | median of margin-free book probabilities, trimmed mean, sharp reference, dispersion. |
| Built Elo / Poisson / Dixon-Coles? | YES | walk-forward on 30 real seasons (see RESULTS.md). |
| Validated calibration? | YES | ECE, reliability + Wilson CIs, slopes, sequential calibration, raw vs calibrated reported. |
| Quantified uncertainty? | YES | Laplace + model dispersion intervals for 1X2, O/U 2.5 and BTTS; market dispersion. |
| Built the NO BET engine? | YES | reason codes incl. edge consumed by margin / removed by calibration / not robust. |
| Built the edge meta-model (EDGE_CONFIDENCE)? | NO | Needs realised edges with odds to train on; placeholder rules (agreement, uncertainty, quality) are used instead. |
| Tracked CLV? | PARTIAL | computed in backtests and paper reconciliation; no real closing odds yet. |
| Modelled correlation? | PARTIAL | exact same-match correlation from the score matrix; cross-match independence assumed (flagged). |
| Built Monte Carlo? | YES | score sampling, slip simulator, bankroll simulator (deterministic seeds). |
| Built portfolio risk / risk of ruin? | PARTIAL | risk limits + bankroll Monte Carlo; no portfolio optimiser (deliberately, until an edge is validated). |
| Protected against Martingale? | YES | forbidden names refused; stake function has no access to history (tested). |
| Implemented walk-forward validation? | YES | `backtesting/walkforward.py`. |
| Implemented nested validation? | YES | `backtesting/nested.py` + `nested` command (inner walk-forward per outer season, holdout skipped, candidates counted); calibration selection is nested too. Default parameters are fixed a priori. |
| Protected the final holdout? | YES | clipping + logged, reason-required access. |
| Accounted for multiple testing? | YES | per-family candidate counts + Bonferroni warning in reports. |
| Built Champion/Challenger? | YES | registry + gates (`gates` command runs the leakage suite). |
| Built the Research Lab? | PARTIAL | synthetic known-truth simulator, experiment registry, gates; no automated experiment scheduler. |
| Built drift detection? | PARTIAL | `quality/drift.py`: league behaviour (home/draw rate, goals), live performance vs backtest expectation, per-selection calibration-in-the-large; runs in `daily`, an ALERT blocks candidates (`DRIFT_ALERT`). Feature/odds-distribution drift not yet implemented; live checks need resolved paper predictions (sample-size guarded). |
| Created live paper predictions? | YES | 10 upcoming Serie A fixtures predicted on 2026-09-29 (all INSUFFICIENT_DATA: no odds). |
| Can every prediction be reproduced? | YES | snapshot fingerprint, model version (+param hash), feature version, cutoffs, calibrator run id stored; data rebuildable from the lake. |
| Can every important data point be traced? | YES | match -> source_match -> raw file hash/row -> manifest URL/time/license. |
| Can the system survive a provider failure? | YES | provider isolation in acquisition, parser-crash isolation in ingestion, task isolation in the daily pipeline (tested). |
| Can the system operate without paid APIs? | YES | no paid service used. |
| Can the system run without CUDA? | YES | CPU only. |
| Did every complex component justify itself? | PARTIAL | Dixon-Coles and weighted Poisson do **not** beat Elo on Serie A 1995-2025 (see RESULTS.md) - reported as such; no ML/ensemble was added. |

## Other directive items not yet done

Lineup/injury/player models (no legal data source integrated), tactical/manager engine,
xG model, advanced ML, ensemble, regime-change detection, market-specific models beyond
1X2/O-U/BTTS/AH derivations, PDF reports, additional sports. The PowerShell scripts were
written for Windows PowerShell 5.1 but could not be executed in the (Linux) build
environment - run `scripts\setup.ps1` first and report any issue.
