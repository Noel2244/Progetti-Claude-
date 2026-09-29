# Architecture

```
DATA DISCOVERY -> ACQUISITION -> RAW LAKE (immutable, hashed) -> CONTRACTS -> NORMALIZATION
  -> ENTITY RESOLUTION -> CANONICAL MATCHES (+conflicts) -> POINT-IN-TIME STORE (as_of)
  -> FEATURES / MODELS (Elo, Poisson, weighted Poisson, Dixon-Coles, climatology, market)
  -> CALIBRATION (sequential, OOS only) -> UNCERTAINTY (Laplace + model dispersion)
  -> MARKET (margin removal, consensus, staleness) -> EDGE / EV -> ABSTENTION (NO BET engine)
  -> CORRELATION (slips) -> STAKING / RISK LIMITS -> REPORTS
  -> LIVE PAPER (immutable, hash-chained) -> RESULT / CLV -> EXPERIMENTS / CHAMPION-CHALLENGER
```

## Package layout (`sports_engine/`)

| Package | Responsibility |
|---|---|
| `core/` | config (`config.yaml` + `.env`), UTC time helpers, hashing, enums, errors, JSON logging with secret redaction, environment audit |
| `data/` | `RawDataLake` (content-addressed, read-only files, JSONL manifests), `PoliteDownloader` (robots, rate limit, retries, resume, conditional GET, SSRF guard, size cap) |
| `providers/` | one adapter per source; common `DataProvider` interface; registry |
| `normalization/` | provider-agnostic records + data contracts |
| `entity/` | competition registry, curated team registry, conservative resolver (registry -> normalized -> fixture co-occurrence -> new entity; ambiguous never merged) |
| `database/` | SQLite schema (immutability triggers), thin access layer |
| `pipeline/` | acquisition pipeline, ingestion (stage/resolve/canonicalise), task runner (retry/checkpoint/partial failure) |
| `quality/` | component-based data quality, coverage matrix, gaps report, historical data report, point-in-time audit |
| `pit/` | `HistoricalStore.as_of(ts) -> PITSnapshot`; decision-time policy with all cutoffs |
| `features/` | versioned, snapshot-based team features |
| `models/` | score-matrix engine, Elo, Poisson family, baselines (climatology, market), champion/challenger gates, registry |
| `market/` | margin removal (5 methods), consensus/best price/dispersion/staleness/outliers, CLV |
| `calibration/` | metrics (log loss, Brier, RPS, ECE, reliability + Wilson CIs, slope/intercept, paired block bootstrap), calibrators + JSON persistence |
| `uncertainty/` | model agreement (max diff, JS divergence), combined intervals |
| `decision/` | candidates, EV/edge, NO BET engine with reason codes, staking (no progression possible), risk limits |
| `correlation/` | slip evaluation: exact same-match joint probabilities from the score matrix, Monte Carlo cross-check |
| `portfolio/` | bankroll Monte Carlo: drawdown, risk of ruin, volatility |
| `backtesting/` | walk-forward engine (point-in-time, sequential calibration, holdout guard, betting simulation), runner service |
| `experiments/` | immutable experiment registry, multiple-testing accounting, holdout access log |
| `paper/` | live paper engine: immutable predictions, versioning, reconciliation, integrity check |
| `research_lab/` | synthetic league/market simulator for known-truth validation |
| `reporting/` | backtest and daily reports (Markdown/JSON/CSV/HTML) |
| `api/` | FastAPI app + static dashboard |

## Design decisions

* **Local-first, CPU-first.** SQLite for storage; DuckDB/pyarrow optional for analytics;
  no GPU code path exists (nothing needs it). Runs on a normal Windows 11 PC.
* **Point-in-time enforced at the data-access layer**, not by convention: models get a
  `PITSnapshot` whose `results()` only contains rows with `result_available_at <= as_of`,
  whose fixture view has no goal columns and a status derived from visible data, and whose
  odds exclude anything with `available_at > as_of` (closing odds are stamped at kickoff).
* **Package name.** The directive suggested `app/`; we use `sports_engine/` to avoid a
  generic top-level name colliding with other installed packages.
* **Our own model implementations** (instead of wrapping a library) so that fitting
  respects snapshots, uncertainty is available, and gradients are verified.
* **Derived data is rebuildable.** Raw files are immutable; every derived table can be
  rebuilt from the lake (`ingest --force`).
* **Immutability in the database.** Paper predictions, paper outcomes, experiments and the
  holdout log are protected by SQLite triggers; paper predictions are also hash-chained.
* **Complexity must earn its place.** Advanced ML, ensembles, neural nets and portfolio
  optimisation are deliberately *not* in the first vertical slice (see `SELF_AUDIT.md`).
