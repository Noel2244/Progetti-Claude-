# Data model

Schema: `sports_engine/database/schema.sql` (SQLite, `schema_version` 1). All timestamps
are UTC `YYYY-MM-DDTHH:MM:SSZ`, so string order equals time order.

## Provenance and staging

| Table | Purpose |
|---|---|
| `source_record` | one row per ingested raw file revision (sha256, provider, dataset, URL, download time, license, terms, parser version, counts) |
| `ingestion_issue` | every contract violation (ERROR = rejected record, WARN = kept + flagged) |
| `source_match` | each source's view of a match (raw team names, resolved ids, goals, kickoff, timestamp quality, stats/extra JSON, raw row pointer) |
| `source_match_stats` | post-match statistics delivered separately (e.g. xG aggregated from events) |
| `source_odds` | odds as delivered, keyed by source record, with `available_at` + timestamp quality |

## Entities

| Table | Purpose |
|---|---|
| `competition` | canonical competitions (`ITA1`, `ENG1`, ... from `entity/registry/competitions.yaml`) |
| `team` | canonical teams; `auto_created=1` when created by the resolver |
| `team_alias` | (source, country, raw name) -> team, with method, confidence, evidence |
| `entity_review` | ambiguous / non-injective names awaiting a human decision (never auto-merged) |

**Club lineages.** Re-founded clubs are mapped to one entity on purpose (e.g. Parma AC ->
Parma FC -> Parma Calcio 1913; Genova 1893 -> Genoa; Lanerossi Vicenza -> Vicenza;
SPAL 1907 -> SPAL 2013). Strength continuity is plausible for modelling; the mapping is
explicit in `teams_ITA.yaml` and easy to change.

## Canonical data

`match` - one row per fixture after merging sources:
`match_id` (deterministic hash of competition, season, home, away[, ordinal]),
`match_date` (local), `kickoff_utc` + `kickoff_time_known` + `timestamp_quality`,
goals, `status`, **`result_available_at`** (the instant the result may be used:
kickoff + 3h league / 4h cup, or next local midnight for date-only matches),
`primary_source`, `sources`, `n_sources`, `has_conflict`, **`score_disputed`**,
merged `stats_json`, `data_version` (hash of contributing raw files).

`odds_snapshot` - (match, source, bookmaker, market, selection, line, odds,
snapshot_type OPENING/PRE_MATCH/CLOSING, **available_at**, timestamp_quality).
`bookmaker.is_aggregate` marks Max/Avg columns (excluded from consensus when real books exist).

`data_conflict` - (entity, field, source_a/value_a, source_b/value_b, resolution, reason).

`data_quality` - component-based quality per competition-season (score + weakest + all components).

## Research, models, live

`experiment` (immutable, content-hashed), `holdout_access` (append-only), `model_registry`
+ `model_event` (champion/challenger lifecycle, never deleted), `backtest_run`,
`paper_prediction` (immutable, hash chain, all cutoffs, payload with model inputs/outputs),
`paper_outcome` (immutable), `journal_entry` (personal notes / manual bets),
`pipeline_run`, `provider_status`, `drift_record`.

## Directive entities -> implementation

| Directive entity | Where |
|---|---|
| Competition, Season, Team, Match, MatchState | `competition`, `match.season`, `team`, `match`, `match.status` |
| OddsSnapshot, Bookmaker, Market, MarketSelection | `odds_snapshot`, `bookmaker`, `odds_snapshot.market/selection` |
| MarketConsensus | computed on demand (`market/consensus.py`), stored in paper payloads |
| Prediction, PredictionSnapshot, FeatureSnapshot | `paper_prediction` (+payload), backtest `predictions.csv`, `features/team_features.FeatureSnapshot` |
| Model, ModelVersion, ModelRun, CalibrationRun, BacktestRun | `model_registry`, `model_event`, `backtest_run`, `models/calibration/*.json` |
| Experiment, ExperimentRun | `experiment` |
| BetCandidate, Portfolio(Selection) | `decision.engine.Candidate`, risk-limited selections in paper/backtest |
| Result, ClosingLine, CLVRecord, BankrollSnapshot, PerformanceRecord | `paper_outcome`, `odds_snapshot` CLOSING, `paper_outcome.clv_*`, `PaperEngine.status()` |
| DataQualityRecord, DriftRecord, SourceRecord, DataConflictRecord | `data_quality`, `drift_record`, `source_record`, `data_conflict` |
| Player, Manager, Venue, Lineup, StartingXI, Substitution, PlayerAvailability, Injury, Suspension, ManagerChange, Event, PlayerStats, ExpectedGoals | **not yet populated** - no legally usable source integrated beyond StatsBomb metadata (managers/venue/referee kept in `source_match.extra_json`, xG in `source_match_stats`). Tables will be added with the first real source; the system reports lineup uncertainty as HIGH meanwhile. |
