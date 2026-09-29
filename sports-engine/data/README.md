# data/ (not committed)

Everything in this folder is local and git-ignored: third-party raw data must never be
committed or redistributed (see `docs/LICENSES.md`).

```
raw/<provider>/<dataset>/<sha256>.<ext>   immutable, read-only, content-addressed
manifests/<provider>.jsonl                append-only provenance (URL, hash, time, license)
metadata/download_cache/                  partial downloads (.part) for resuming
inbox/                                    manual imports (matches_*.csv, odds_*.csv, football_data/*.csv)
sports_engine.sqlite                      canonical database (rebuildable from raw/ with `ingest --force`)
normalized/ snapshots/ features/ conflicts/   reserved for exports
```

Rebuild everything on a new machine: `scripts\download_history.ps1` then `scripts\validate_data.ps1`.
