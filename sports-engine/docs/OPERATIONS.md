# Operations

## First-time setup (Windows 11, PowerShell)

```powershell
cd sports-engine
.\scripts\setup.ps1          # venv + dependencies + folders + environment audit
.\scripts\download_history.ps1
.\scripts\validate_data.ps1  # ingest, integrity, coverage, point-in-time audit
.\scripts\backtest.ps1       # Serie A walk-forward (writes reports\backtests\<run>)
.\scripts\daily.ps1          # daily pipeline + paper predictions + daily report
.\scripts\start.ps1          # dashboard at http://127.0.0.1:8000
```

Linux/macOS: `scripts/*.sh` equivalents, or call `python -m sports_engine <command>`.

## Daily routine

`daily` runs, each step isolated with retries and checkpoints (`pipeline_run` table):

1. download (conditional; closed seasons never re-downloaded) - provider failures degrade, never crash
2. import inbox (manual results / timestamped odds / football-data CSVs)
3. ingest (critical) - contracts, entities, canonical matches, conflicts
4. quality + point-in-time audit
5. paper reconcile (results, closing odds, CLV)
6. paper predict (upcoming `paper.horizon_days`), immutable
7. daily report (`reports/daily/daily_YYYY-MM-DD.md|html|json|csv`)

Schedule it with Windows Task Scheduler (e.g. 08:30 and 18:30) using `scripts\daily.ps1`.
Re-running is cheap: unchanged inputs produce no new predictions ("skipped_unchanged").

## Pre-match updates

Run `python -m sports_engine paper run` whenever new information arrives (new odds file,
new results). A new prediction version is written only if the data snapshot, the odds or
the model version changed - event-driven rather than on a fixed T-48h/T-24h/... clock.
The configurable checkpoints can be scheduled the same way.

## Odds for live paper mode

Without odds the engine still predicts but every selection is INSUFFICIENT_DATA. Options:
* enable football-data (private use) - `fixtures.csv` odds carry exact capture times;
* or drop `data/inbox/odds_<anything>.csv` files (format in DATA_SOURCES.md) with a
  `captured_at` timestamp, e.g. copied manually from a bookmaker you use.

## Retraining

Models are refitted from the point-in-time snapshot at every paper run (cheap). Calibrators
change only when a new backtest is run and saved (`backtest` writes `models/calibration`).
Every backtest is logged as an experiment; retraining events are therefore traceable.
Retrain triggers to watch: calibration drift in paper outcomes, a new season, a regime change
(promotions), new data sources.

## Backups

Copy `data/` (raw lake + manifests + SQLite) and `models/`. Raw files are content-addressed,
so an incremental copy is safe. `python -m sports_engine validate-data` verifies every
raw file hash after a restore.

## Health

`python -m sports_engine report data-health|model-health`, `paper status`, `paper verify`,
dashboard "System health", `reports/logs/engine.log` (JSON lines).
