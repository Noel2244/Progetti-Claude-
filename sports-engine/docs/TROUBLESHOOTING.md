# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `football_data is opt-in` in `sources` / download | Intended. Read LICENSES.md, then set `enabled` and `terms_acknowledged` in `config.yaml` (private, non-commercial use only). |
| Provider `UNAVAILABLE: robots.txt disallows access` | The site forbids automated access for our user agent. Do not change the UA to get around it; use manual import instead. |
| Provider `DEGRADED` | Network or HTTP errors after retries; the other providers still ran. Re-run later; conditional requests keep it cheap. |
| `missing` datasets in the download report | The upstream file does not exist (e.g. openfootball Serie A 2010-2013). Shown as coverage gaps. |
| `PARSER_CRASH` in `validate-data` | An upstream format change. The file is kept in the lake; fix the parser, bump its `PARSER_VERSION`, then `ingest` re-parses automatically. |
| `entity_review` rows | Ambiguous team names are never merged automatically. Add the alias to `sports_engine/entity/registry/teams_<COUNTRY>.yaml`, then `ingest --force`. |
| Paper run says "no fixtures in the next N days" | International break or source lag. `--horizon 14`, or check `next_fixture_date` in the output. |
| All selections `INSUFFICIENT_DATA` / `NO_MARKET_ODDS` | No odds visible at decision time. See OPERATIONS.md "Odds for live paper mode". |
| `CALIBRATION_UNAVAILABLE` everywhere | Run a backtest first; it saves the live calibrators to `models/calibration/`. |
| `paper verify` reports problems | The paper table was modified outside the engine. Restore `data/sports_engine.sqlite` from backup. |
| `HoldoutAccessError` | You asked for the final holdout without `--holdout-reason`. Each access is logged; think twice. |
| Backtest is slow | ~30 seasons x 6 models takes tens of minutes on 4 cores (goal models refit weekly with uncertainty). Use fewer models (`--models elo,dixon_coles`) for exploration. |
| PowerShell refuses to run scripts | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| `database is locked` | Two processes writing at once (e.g. daily + backtest). Run them sequentially; SQLite uses WAL and a 30 s timeout. |
