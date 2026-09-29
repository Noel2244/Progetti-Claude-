# Data sources

Every source is wrapped by an adapter in `sports_engine/providers/` implementing the
common `DataProvider` interface (`discover`, `parse`, `followups`, `fetch_*`).
Provider formats never reach the core domain: adapters emit
`SourceMatchRecord` / `SourceOddsRecord` (see `normalization/records.py`).
If a provider disappears or fails, the pipeline records it (`provider_status`) and
continues with the others.

| Provider | Tier | Classes | Content | Coverage (Serie A) | Timestamps |
|---|---|---|---|---|---|
| `engsoccerdata` | SECONDARY | LONG_TERM, POINT_IN_TIME_READY | results | 1929/30 - 2024/25 | DATE_ONLY |
| `openfootball` | SECONDARY | MEDIUM_TERM, RECENT, LIVE_OUT_OF_SAMPLE | results, HT, kickoff, fixtures | 2013/14 - 2026/27 (2010-2013 files do not exist) | EXACT (local time) |
| `statsbomb` | REPUTABLE_STRUCTURED | POST_MATCH_ONLY, NON_POINT_IN_TIME | match metadata, managers, referee, venue; events/xG opt-in | 1986/87, 2015/16 | APPROXIMATE (see inventory) |
| `football_data` (opt-in) | REPUTABLE_STRUCTURED | LONG_TERM, POINT_IN_TIME_READY, LIVE | results 1993/94-, stats, 1X2/OU/AH odds 2000/01-, closing odds 2019/20-, fixtures.csv | user-run | kickoff EXACT from 2019/20; odds APPROXIMATE/EXACT |
| `local_csv` | UNVERIFIED | LIVE_OUT_OF_SAMPLE | user results/fixtures/**timestamped** odds | - | EXACT (user-supplied capture time) |

## Source hierarchy (directive section 30)

`OFFICIAL_COMPETITION > OFFICIAL_CLUB > OFFICIAL_TEAM > REPUTABLE_STRUCTURED >
REPUTABLE_JOURNALISM > SECONDARY > SOCIAL_MEDIA > UNVERIFIED` (`core/enums.SourceTier`).

Field-level priority used when sources disagree (`config.yaml: source_priority`):

* results: statsbomb > football_data > openfootball > engsoccerdata > local_csv
* kickoff: football_data > openfootball > local_csv > statsbomb > engsoccerdata
  (StatsBomb was demoted after its kickoff times proved timezone-inconsistent)

Disagreements are **never silently overwritten**: each one is written to
`data_conflict` with both values, the winner and the reason.

## Manual import formats (`data/inbox/`)

`matches_*.csv`: `competition_id,season,date,time,home,away,home_goals,away_goals,status`

`odds_*.csv`: `competition_id,date,home,away,bookmaker,market,selection,line,odds,snapshot_type,captured_at`
(`captured_at` is mandatory, ISO-8601 with timezone - odds without a capture time
cannot be used point-in-time and are rejected).

`football_data/*.csv`: CSV files you downloaded yourself from football-data.co.uk.

## Adding a provider

1. Subclass `DataProvider`, fill `ProviderInfo` (license, terms, tier, hosts, classes).
2. Implement `discover()` and `parse()`; emit only normalized records.
3. Register it in `providers/registry.py`, add hosts/rate limit in `config.yaml`.
4. Add parser tests with **invented** fixture rows (never commit third-party data).
5. Document license/terms in `docs/LICENSES.md` before enabling it.
