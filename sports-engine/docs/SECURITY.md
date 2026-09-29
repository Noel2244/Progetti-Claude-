# Security

| Area | Measure |
|---|---|
| Secrets | Only in a local `.env` (git-ignored; template `.env.example`). Never in `config.yaml`, never logged: the JSON log handler redacts values of env vars named `*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`. |
| Network | `PoliteDownloader`: http(s) only, per-provider host allow-list (checked again after redirects -> SSRF guard), honest UA, robots.txt, rate limits, size cap, timeouts. |
| Downloaded content | Treated as data only: parsed with `csv`/`json`/pandas, **never executed or imported**. |
| Paths | Dataset keys and extensions validated (`safe_key`, no `..`, no absolute paths), targets checked to stay inside `data/raw`. API never takes file paths from requests. |
| Subprocess | Only `git` and `pytest` with fixed argument lists (`shell=False`), timeouts. |
| Serialisation | JSON only (no pickle) for models/calibrators. |
| Database | Parameterised SQL everywhere; immutability triggers on paper predictions/outcomes, experiments, holdout log; paper predictions hash-chained (`paper verify`). |
| API | Binds to 127.0.0.1; the CLI refuses a non-local host unless `SPORTS_ENGINE_API_TOKEN` is set; GET endpoints are read-only; POST `/journal` requires `X-API-Token` when a token exists; typed/bounded query params; ids validated by regex. |
| Money | No bookmaker integration exists; `mode` must be `paper` (config loader refuses anything else). |
| Dependencies | Small, mainstream set. Run `pip-audit` (or `uv pip audit` where available) periodically: `scripts/test.ps1 -Audit`. |

## Reporting a problem

This is a personal project; record security notes in the journal and fix before use.
