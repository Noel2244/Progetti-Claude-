# Data acquisition

`HistoricalDataAcquisitionPipeline` (`pipeline/acquisition.py`) + `PoliteDownloader`
(`data/download.py`) + `RawDataLake` (`data/lake.py`).

## Steps

1. **Discover** datasets per provider/competition/season (`provider.discover`), plus
   follow-ups found inside index files (StatsBomb `competitions.json` -> season files).
2. **Evaluate / license**: providers declare license, terms URL, tier, restrictions, hosts;
   opt-in providers (`football_data`) are skipped with a reason until acknowledged.
3. **Download**: honest UA, robots.txt, per-host rate limit (1-3 s), retries with exponential
   backoff and `Retry-After`, resumable `.part` files with HTTP Range, conditional requests
   (ETag / Last-Modified), 250 MB cap, host allow-list also after redirects.
4. **Preserve**: content-addressed file `data/raw/<provider>/<dataset>/<sha256>.<ext>`,
   written atomically and made read-only; identical content is stored once.
5. **Manifest**: append-only `data/manifests/<provider>.jsonl` with URL, sha256, size,
   download time, ETag/Last-Modified, content type, license, terms, dataset metadata.
6. **Skip immutable data**: closed seasons already in the lake are never re-downloaded;
   current-season files are re-checked conditionally, and every new revision is kept
   (revision history = source revision behaviour).
7. **Gaps**: HTTP 404 -> `missing` (coverage gap); robots disallow -> provider UNAVAILABLE,
   never bypassed; other failures -> provider DEGRADED while the others continue.
8. **Parallelism**: one worker per provider (parallel across providers, serial per host).

## Commands

```
python -m sports_engine download-history --competitions ITA1            # default providers
python -m sports_engine download-history --providers openfootball --seasons 2013-2026
python -m sports_engine import-inbox                                     # manual files
python -m sports_engine ingest                                           # parse+resolve+merge
python -m sports_engine coverage                                         # matrix + gaps
python -m sports_engine validate-data                                    # integrity + audit
```

Windows: `scripts\download_history.ps1`, `scripts\validate_data.ps1`.

## Ingestion (`pipeline/ingest.py`)

For the latest revision of each dataset: parse -> **data contracts** (types, ranges,
nullability, duplicates, timestamps, entity references; errors rejected, warnings kept) ->
replace that dataset's staged rows (transaction) -> **entity resolution** -> **canonical
merge** (cluster per competition/season/home/away, conflict records, result availability,
odds materialisation). A parser crash on one file is recorded and never stops the run.
Idempotent: re-running with unchanged inputs keeps every id stable.

## Expanding coverage

`competitions` / `expansion_competitions` in `config.yaml`. The registry already maps
ENG1, ESP1, GER1, FRA1, UCL (+UEL/UECL for openfootball). Team registries for other
countries start empty: the resolver creates entities from the first source and aligns later
sources by normalized name and fixture co-occurrence; ambiguous names wait in
`entity_review`.
