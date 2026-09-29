-- Personal Sports Research Engine - SQLite schema (schema_version 1)
-- All timestamps: UTC ISO-8601 'YYYY-MM-DDTHH:MM:SSZ' (lexicographic == chronological).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ------------------------------------------------------------------ provenance
CREATE TABLE IF NOT EXISTS source_record (
    raw_sha256      TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,
    dataset_key     TEXT NOT NULL,
    url             TEXT,
    downloaded_at   TEXT NOT NULL,
    license_id      TEXT,
    terms_ref       TEXT,
    acquisition     TEXT NOT NULL DEFAULT 'download',
    parser_version  TEXT,
    ingested_at     TEXT,
    n_matches       INTEGER,
    n_odds          INTEGER,
    n_errors        INTEGER,
    n_warnings      INTEGER
);

CREATE TABLE IF NOT EXISTS ingestion_issue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_sha256   TEXT,
    provider     TEXT,
    severity     TEXT NOT NULL,
    code         TEXT NOT NULL,
    message      TEXT,
    record_key   TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_issue_provider ON ingestion_issue(provider, severity);

-- ------------------------------------------------------------------ entities
CREATE TABLE IF NOT EXISTS competition (
    competition_id TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    country        TEXT,
    tier           INTEGER,
    type           TEXT,
    timezone       TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    schema_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team (
    team_id        TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    country        TEXT,
    auto_created   INTEGER NOT NULL DEFAULT 0,
    source         TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    schema_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_alias (
    source      TEXT NOT NULL,
    country     TEXT NOT NULL,
    alias       TEXT NOT NULL,
    team_id     TEXT NOT NULL REFERENCES team(team_id),
    method      TEXT NOT NULL,     -- REGISTRY | NORMALIZED | COOCCURRENCE | NEW_ENTITY
    confidence  REAL NOT NULL,
    evidence    TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (source, country, alias)
);

CREATE TABLE IF NOT EXISTS entity_review (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT NOT NULL,
    source       TEXT NOT NULL,
    country      TEXT,
    raw_name     TEXT NOT NULL,
    candidates   TEXT,
    reason       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'OPEN',
    created_at   TEXT NOT NULL,
    UNIQUE (entity_type, source, country, raw_name)
);

-- ------------------------------------------------------------------ matches
CREATE TABLE IF NOT EXISTS source_match (
    source            TEXT NOT NULL,
    source_match_key  TEXT NOT NULL,
    dataset_key       TEXT NOT NULL,
    competition_id    TEXT NOT NULL,
    season            TEXT NOT NULL,
    season_start_year INTEGER NOT NULL,
    match_date        TEXT NOT NULL,
    kickoff_utc       TEXT,
    kickoff_local     TEXT,
    timestamp_quality TEXT NOT NULL,
    home_team_raw     TEXT NOT NULL,
    away_team_raw     TEXT NOT NULL,
    home_team_id      TEXT,
    away_team_id      TEXT,
    home_goals        INTEGER,
    away_goals        INTEGER,
    ht_home_goals     INTEGER,
    ht_away_goals     INTEGER,
    status            TEXT NOT NULL,
    round             TEXT,
    venue             TEXT,
    referee           TEXT,
    stats_json        TEXT,
    extra_json        TEXT,
    raw_sha256        TEXT,
    raw_row           INTEGER,
    ingested_at       TEXT NOT NULL,
    match_id          TEXT,
    PRIMARY KEY (source, source_match_key)
);
CREATE INDEX IF NOT EXISTS ix_sm_match ON source_match(match_id);
CREATE INDEX IF NOT EXISTS ix_sm_comp ON source_match(competition_id, season);
CREATE INDEX IF NOT EXISTS ix_sm_dataset ON source_match(source, dataset_key);

-- post-match statistics delivered separately from the match record (e.g. xG from event files)
CREATE TABLE IF NOT EXISTS source_match_stats (
    source           TEXT NOT NULL,
    dataset_key      TEXT NOT NULL,
    source_match_key TEXT NOT NULL,
    stats_json       TEXT NOT NULL,
    raw_sha256       TEXT,
    PRIMARY KEY (source, dataset_key, source_match_key)
);

-- odds as delivered by a source, before canonical match ids exist
CREATE TABLE IF NOT EXISTS source_odds (
    source            TEXT NOT NULL,
    dataset_key       TEXT NOT NULL,
    source_match_key  TEXT NOT NULL,
    bookmaker         TEXT NOT NULL,
    market            TEXT NOT NULL,
    selection         TEXT NOT NULL,
    line              REAL,
    odds              REAL NOT NULL,
    snapshot_type     TEXT NOT NULL,
    available_at      TEXT NOT NULL,
    timestamp_quality TEXT NOT NULL,
    raw_sha256        TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_source_odds ON source_odds(
    source, source_match_key, bookmaker, market, selection, IFNULL(line, -9999.0), snapshot_type, available_at);
CREATE INDEX IF NOT EXISTS ix_so_dataset ON source_odds(source, dataset_key);

CREATE TABLE IF NOT EXISTS match (
    match_id            TEXT PRIMARY KEY,
    competition_id      TEXT NOT NULL,
    season              TEXT NOT NULL,
    season_start_year   INTEGER NOT NULL,
    match_date          TEXT NOT NULL,       -- local calendar date
    kickoff_utc         TEXT,                -- exact kickoff when known
    kickoff_time_known  INTEGER NOT NULL,
    timestamp_quality   TEXT NOT NULL,
    home_team_id        TEXT NOT NULL,
    away_team_id        TEXT NOT NULL,
    home_goals          INTEGER,
    away_goals          INTEGER,
    ht_home_goals       INTEGER,
    ht_away_goals       INTEGER,
    status              TEXT NOT NULL,
    result_available_at TEXT,                -- earliest time the result may be used
    primary_source      TEXT NOT NULL,
    sources             TEXT NOT NULL,       -- JSON list
    n_sources           INTEGER NOT NULL,
    has_conflict        INTEGER NOT NULL DEFAULT 0,
    score_disputed      INTEGER NOT NULL DEFAULT 0,  -- sources disagree on the score (e.g. awarded result)
    stats_json          TEXT,
    data_version        TEXT NOT NULL,
    schema_version      TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_match_comp_date ON match(competition_id, match_date);
CREATE INDEX IF NOT EXISTS ix_match_home ON match(home_team_id);
CREATE INDEX IF NOT EXISTS ix_match_away ON match(away_team_id);
CREATE INDEX IF NOT EXISTS ix_match_available ON match(result_available_at);

-- ------------------------------------------------------------------ odds
CREATE TABLE IF NOT EXISTS bookmaker (
    bookmaker_id TEXT PRIMARY KEY,
    is_aggregate INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS odds_snapshot (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id          TEXT NOT NULL,
    source            TEXT NOT NULL,
    bookmaker         TEXT NOT NULL,
    market            TEXT NOT NULL,
    selection         TEXT NOT NULL,
    line              REAL,
    odds              REAL NOT NULL CHECK (odds > 1.0),
    snapshot_type     TEXT NOT NULL,
    available_at      TEXT NOT NULL,
    timestamp_quality TEXT NOT NULL,
    raw_sha256        TEXT,
    ingested_at       TEXT NOT NULL
);
-- expression index: NULL lines must still de-duplicate (NULLs are distinct in UNIQUE)
CREATE UNIQUE INDEX IF NOT EXISTS ux_odds_snapshot ON odds_snapshot(
    match_id, source, bookmaker, market, selection, IFNULL(line, -9999.0), snapshot_type, available_at);
CREATE INDEX IF NOT EXISTS ix_odds_match ON odds_snapshot(match_id, market);
CREATE INDEX IF NOT EXISTS ix_odds_available ON odds_snapshot(available_at);

-- ------------------------------------------------------------------ quality & conflicts
CREATE TABLE IF NOT EXISTS data_conflict (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type       TEXT NOT NULL,
    entity_id         TEXT NOT NULL,
    field             TEXT NOT NULL,
    source_a          TEXT NOT NULL,
    value_a           TEXT,
    source_b          TEXT NOT NULL,
    value_b           TEXT,
    resolution        TEXT NOT NULL,
    resolution_reason TEXT NOT NULL,
    detected_at       TEXT NOT NULL,
    UNIQUE (entity_type, entity_id, field, source_a, source_b)
);

CREATE TABLE IF NOT EXISTS data_quality (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope       TEXT NOT NULL,     -- competition_season | provider | match
    scope_id    TEXT NOT NULL,
    score       REAL NOT NULL,
    weakest     TEXT,
    components  TEXT NOT NULL,     -- JSON; always reported next to the score
    computed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dq_scope ON data_quality(scope, scope_id);

-- ------------------------------------------------------------------ research / models
CREATE TABLE IF NOT EXISTS experiment (
    experiment_id     TEXT PRIMARY KEY,
    version           INTEGER NOT NULL,
    parent_id         TEXT,
    family            TEXT NOT NULL,     -- research question; used for multiple-testing accounting
    name              TEXT NOT NULL,
    hypothesis        TEXT,
    created_at        TEXT NOT NULL,
    dataset_version   TEXT,
    feature_version   TEXT,
    code_version      TEXT,
    model_version     TEXT,
    hyperparameters   TEXT,
    random_seed       INTEGER,
    training_period   TEXT,
    validation_period TEXT,
    test_period       TEXT,
    used_holdout      INTEGER NOT NULL DEFAULT 0,
    n_candidates      INTEGER NOT NULL DEFAULT 1,
    metrics           TEXT,
    notes             TEXT,
    content_hash      TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS experiment_no_update BEFORE UPDATE ON experiment
BEGIN SELECT RAISE(ABORT, 'experiment records are immutable; create a new version'); END;
CREATE TRIGGER IF NOT EXISTS experiment_no_delete BEFORE DELETE ON experiment
BEGIN SELECT RAISE(ABORT, 'experiment records are immutable'); END;

CREATE TABLE IF NOT EXISTS holdout_access (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    accessed_at   TEXT NOT NULL,
    experiment_id TEXT,
    holdout_start TEXT NOT NULL,
    reason        TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS holdout_no_update BEFORE UPDATE ON holdout_access
BEGIN SELECT RAISE(ABORT, 'holdout log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS holdout_no_delete BEFORE DELETE ON holdout_access
BEGIN SELECT RAISE(ABORT, 'holdout log is append-only'); END;

CREATE TABLE IF NOT EXISTS model_registry (
    model_key    TEXT PRIMARY KEY,   -- name@version
    name         TEXT NOT NULL,
    version      TEXT NOT NULL,
    role         TEXT NOT NULL,      -- CHAMPION | CHALLENGER | RETIRED
    config       TEXT,
    gates        TEXT,               -- JSON quality-gate results
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_key   TEXT NOT NULL,
    event       TEXT NOT NULL,       -- REGISTERED | PROMOTED | DEMOTED | RETIRED | RETRAINED
    reason      TEXT,
    details     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_run (
    run_id        TEXT PRIMARY KEY,
    experiment_id TEXT,
    created_at    TEXT NOT NULL,
    config        TEXT NOT NULL,
    summary       TEXT,
    report_dir    TEXT
);

-- ------------------------------------------------------------------ live paper (immutable)
CREATE TABLE IF NOT EXISTS paper_prediction (
    seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id       TEXT NOT NULL UNIQUE,
    created_at          TEXT NOT NULL,     -- model run time
    prediction_timestamp TEXT NOT NULL,
    data_cutoff         TEXT NOT NULL,
    feature_cutoff      TEXT NOT NULL,
    odds_cutoff         TEXT NOT NULL,
    lineup_cutoff       TEXT,
    match_id            TEXT NOT NULL,
    competition_id      TEXT NOT NULL,
    kickoff_utc         TEXT,
    model_name          TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    feature_version     TEXT NOT NULL,
    market              TEXT NOT NULL,
    selection           TEXT NOT NULL,
    line                REAL,
    model_prob          REAL NOT NULL,
    prob_low            REAL,
    prob_high           REAL,
    market_prob         REAL,
    odds                REAL,
    bookmaker           TEXT,
    edge                REAL,
    ev                  REAL,
    data_quality        REAL,
    status              TEXT NOT NULL,
    reasons             TEXT NOT NULL,
    stake_fraction      REAL NOT NULL DEFAULT 0,
    snapshot_fingerprint TEXT NOT NULL,
    supersedes          TEXT,
    payload             TEXT,
    prev_hash           TEXT NOT NULL,
    row_hash            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pp_match ON paper_prediction(match_id);
CREATE TRIGGER IF NOT EXISTS paper_prediction_no_update BEFORE UPDATE ON paper_prediction
BEGIN SELECT RAISE(ABORT, 'paper predictions are immutable; insert a new version'); END;
CREATE TRIGGER IF NOT EXISTS paper_prediction_no_delete BEFORE DELETE ON paper_prediction
BEGIN SELECT RAISE(ABORT, 'paper predictions are immutable'); END;

CREATE TABLE IF NOT EXISTS paper_outcome (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id     TEXT NOT NULL UNIQUE REFERENCES paper_prediction(prediction_id),
    reconciled_at     TEXT NOT NULL,
    home_goals        INTEGER,
    away_goals        INTEGER,
    outcome           TEXT NOT NULL,   -- WIN | LOSE | PUSH | VOID | NOT_BET_HIT | NOT_BET_MISS
    closing_odds      REAL,
    closing_fair_prob REAL,
    clv_price         REAL,
    clv_fair          REAL,
    pnl_units         REAL,
    log_loss          REAL,
    brier             REAL
);
CREATE TRIGGER IF NOT EXISTS paper_outcome_no_update BEFORE UPDATE ON paper_outcome
BEGIN SELECT RAISE(ABORT, 'paper outcomes are immutable'); END;
CREATE TRIGGER IF NOT EXISTS paper_outcome_no_delete BEFORE DELETE ON paper_outcome
BEGIN SELECT RAISE(ABORT, 'paper outcomes are immutable'); END;

-- ------------------------------------------------------------------ personal journal / manual bets
CREATE TABLE IF NOT EXISTS journal_entry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    prediction_id TEXT,
    match_id      TEXT,
    kind          TEXT NOT NULL,     -- note | manual_bet | review
    selection_reason TEXT,
    rejection_reason TEXT,
    model_expectation TEXT,
    market_expectation TEXT,
    my_expectation TEXT,
    what_happened  TEXT,
    randomness     TEXT,
    model_error    TEXT,
    what_to_change TEXT,
    stake          REAL,
    odds           REAL,
    result         TEXT,
    note           TEXT
);

-- ------------------------------------------------------------------ operations
CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id      TEXT NOT NULL,
    task        TEXT NOT NULL,
    status      TEXT NOT NULL,     -- RUNNING | OK | FAILED | SKIPPED | DEGRADED
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    attempts    INTEGER NOT NULL DEFAULT 1,
    details     TEXT,
    PRIMARY KEY (run_id, task)
);

CREATE TABLE IF NOT EXISTS provider_status (
    provider   TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    status     TEXT NOT NULL,      -- OK | UNAVAILABLE | DISABLED | DEGRADED
    message    TEXT,
    PRIMARY KEY (provider, checked_at)
);

CREATE TABLE IF NOT EXISTS drift_record (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at TEXT NOT NULL,
    scope       TEXT NOT NULL,
    metric      TEXT NOT NULL,
    reference   REAL,
    current     REAL,
    statistic   REAL,
    status      TEXT NOT NULL,     -- OK | WARN | ALERT
    action      TEXT,              -- NONE | REVIEW | RETRAIN | DOWNWEIGHT | RETIRE
    details     TEXT
);
