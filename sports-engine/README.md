# Personal Sports Analytics & Betting Research Engine

A local-first, CPU-first research system that estimates football match probabilities,
compares them with market prices, quantifies uncertainty and **abstains whenever the
evidence is insufficient**. Private personal use, paper mode only.

It is **not** a bookmaker, a tipster, a guaranteed-profit system or an execution bot.
It never places bets, never uses Martingale/loss-chasing staking, and treats
"NO BET", "I don't know", "the data is insufficient" and "the models disagree" as
successful outputs.

## Status: first vertical slice (Serie A)

| Layer | State |
|---|---|
| Historical data | 29,584 Serie A matches, 1929/30 - 2026/27 fixtures, from 3 open sources, immutable hashed raw lake, provenance manifests, conflicts recorded |
| Point-in-time | `as_of(ts)` enforced at the data-access layer; leakage test-suite (future perturbation, canaries) |
| Models | climatology, Elo, Poisson, time-weighted Poisson, Dixon-Coles, market baseline; score-matrix engine; Laplace uncertainty |
| Validation | walk-forward backtest, sequential calibration, block-bootstrap comparisons, holdout guard, experiment registry, promotion gates |
| Decision | margin removal (5 methods), consensus, stale/outlier detection, edge, EV, NO BET engine with reasons, conservative Kelly, risk limits, CLV |
| Live | immutable, hash-chained paper predictions + reconciliation |
| Interfaces | CLI, PowerShell scripts, FastAPI + dashboard, Markdown/HTML/JSON/CSV reports |

Results of the latest real walk-forward run are in [`docs/RESULTS.md`](docs/RESULTS.md).

**Important limitation:** no bookmaker odds are included out of the box. The main free
historical odds source (football-data.co.uk) is for private use and blocks AI agents, so it
is **opt-in and must be enabled and run by you** (see [`docs/LICENSES.md`](docs/LICENSES.md)).
Until odds are present, the engine can evaluate probability quality but cannot answer the
only question that matters for betting - *does the model add information beyond the
market?* - and every live selection is `INSUFFICIENT_DATA`.

## Quick start (Windows 11, PowerShell)

```powershell
cd sports-engine
.\scripts\setup.ps1            # venv, dependencies, folders, environment audit
.\scripts\download_history.ps1 # open sources -> immutable raw lake
.\scripts\validate_data.ps1    # ingest, entity resolution, conflicts, coverage, PIT audit
.\scripts\backtest.ps1         # Serie A walk-forward 1995-2025 (holdout from 2025-07-01 untouched)
.\scripts\daily.ps1            # daily pipeline + live paper predictions + report
.\scripts\start.ps1            # dashboard: http://127.0.0.1:8000
.\scripts\test.ps1             # full test-suite (add -LeakageOnly / -Audit)
```

Optional, after reading its terms (private, non-commercial use only): enable football-data
in `config.yaml` (`providers.football_data.enabled` and `terms_acknowledged`), or put
manually downloaded CSVs in `data\inbox\football_data\`, then re-run `download_history` and
`validate_data`. Timestamped odds of your own can go in `data\inbox\odds_*.csv`.

Linux/macOS: `./scripts/se.sh <command>` or `python -m sports_engine <command>`.

## Commands

`python -m sports_engine --help` - `audit-env`, `sources`, `download-history`, `import-inbox`,
`ingest`, `validate-data`, `coverage`, `pit-audit`, `backtest`, `gates`, `paper run|reconcile|status|verify`,
`daily`, `report daily|data-health|model-health`, `experiments`, `models`, `journal`,
`simulate --scenario efficient|biased`, `serve`.

## Documentation

Architecture and data: [ARCHITECTURE](docs/ARCHITECTURE.md), [DATA_MODEL](docs/DATA_MODEL.md),
[DATA_SOURCES](docs/DATA_SOURCES.md), [LICENSES](docs/LICENSES.md),
[HISTORICAL_DATA_INVENTORY](docs/HISTORICAL_DATA_INVENTORY.md),
[DATA_COVERAGE_MATRIX](docs/DATA_COVERAGE_MATRIX.md), [DATA_ACQUISITION](docs/DATA_ACQUISITION.md),
[POINT_IN_TIME_AUDIT](docs/POINT_IN_TIME_AUDIT.md), [REPOSITORY_RESEARCH](docs/REPOSITORY_RESEARCH.md).
Modelling: [MODEL_METHODOLOGY](docs/MODEL_METHODOLOGY.md), [CALIBRATION](docs/CALIBRATION.md),
[UNCERTAINTY_ENGINE](docs/UNCERTAINTY_ENGINE.md), [BACKTESTING](docs/BACKTESTING.md),
[MARKET_ENGINE](docs/MARKET_ENGINE.md), [CORRELATION_ENGINE](docs/CORRELATION_ENGINE.md),
[RISK_ENGINE](docs/RISK_ENGINE.md), [EXPERIMENTS](docs/EXPERIMENTS.md), [RESEARCH_LAB](docs/RESEARCH_LAB.md).
Operations: [OPERATIONS](docs/OPERATIONS.md), [SECURITY](docs/SECURITY.md),
[TROUBLESHOOTING](docs/TROUBLESHOOTING.md), [ENVIRONMENT_AUDIT](docs/ENVIRONMENT_AUDIT.md).
Honest status against the directive: [SELF_AUDIT](docs/SELF_AUDIT.md), [RESULTS](docs/RESULTS.md).

## Data policy in one paragraph

Raw third-party data lives only in your local `data/` folder (git-ignored), content-hashed
and read-only, with a manifest recording where and when every file came from and under
which terms. Sources are used only as their terms allow; robots.txt and rate limits are
honoured and never bypassed; paid services are never required.
