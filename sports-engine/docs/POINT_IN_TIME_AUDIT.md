# Point-in-time audit

## Principle

Every prediction must be reconstructable exactly as it would have been made at its
decision time. The **data-access layer** enforces it: models receive
`HistoricalStore.as_of(t)` and nothing else.

| Data | Visible when | Stamped by |
|---|---|---|
| Result, exact kickoff | `kickoff + 3h` (league) / `+4h` (cup) | ingestion (`result_available_at`) |
| Result, date only | 00:00 local on the next day | ingestion |
| Fixture schedule | always (status derived from visible results only) | snapshot view |
| Pre-match odds, football-data results files | conservative collection estimate: Friday 18:00 UK (Fri-Mon matches) / Tuesday 18:00 UK (Tue-Thu), capped at kickoff-30min; `APPROXIMATE` | provider |
| Pre-match odds, football-data `fixtures.csv` | our download time; `EXACT` | provider |
| Closing odds | kickoff (never before) | provider |
| User odds (`data/inbox`) | mandatory `captured_at` | provider |
| StatsBomb events/xG | post-match; dataset itself NON_POINT_IN_TIME | provider |

## Decision-time policy (backtests)

A price can only be taken if it exists at decision time. Deciding on Saturday with Friday's
price *and* Saturday's information would book a price that may be gone (stale-price
optimism). So:

* pre-match odds exist -> decide at the latest snapshot that is at least 60 min before
  kickoff (features cut at the same instant);
* otherwise exact kickoff -> kickoff - 60 min;
* otherwise (date only) -> 00:00 local on match day (only earlier days' results are used).

For date-only matches a pre-match snapshot is used only if it was available by 12:00 local
on match day; midweek date-only odds (collected Tuesday afternoon) are therefore not used -
a deliberate loss of data in exchange for no look-ahead.

## Automated checks

* `python -m sports_engine pit-audit` (exit code 2 on failure): finished matches without
  availability, results available before kickoff or in the future, pre-match odds at/after
  kickoff, closing odds before kickoff, odds without timestamps; plus timestamp-quality
  distribution by season.
* Test-suite (blocks promotion): `test_point_in_time.py` (as_of semantics, inclusive
  cut-off, fingerprints, cutoff policy), `test_temporal_leakage.py` (randomising every
  future result and odds leaves predictions bit-identical for all six models; row order
  irrelevant; incremental Elo == fresh fit), `test_feature_leakage.py` (features and
  league normalisers invariant to the future; no target columns),
  `test_future_information.py` (every prediction before kickoff, fit time <= decision time,
  market model never uses closing prices, holdout clipping, calibration only from prior
  seasons, disputed scores excluded).

## Audit result for the build-session database (Serie A)

All ERROR checks passed (see `reports/pit_audit.json`). Timestamp quality: 24,524 matches
DATE_ONLY (1929/30 - 2012/13, plus 260 future 2026/27 fixtures that have no kickoff time yet;
the StatsBomb 1986/87 kickoff is APPROXIMATE and therefore not used), 5,060 EXACT (2013/14
onward from openfootball). No odds are present in the session database, so every odds check is vacuous there;
they are exercised by the synthetic and fixture tests.

## Known residual risks (documented, not hidden)

* **Revisions.** Canonical data reflect the latest revision of each source. A later
  correction (e.g. an awarded result) is used in backtests as if known on match day. Awarded
  results are caught as disputed when sources disagree; single-source corrections are not.
* **Approximate odds timestamps** (football-data pre-closing) rely on the published
  collection schedule; the true time is unknown. Backtests using them are labelled
  approximate point-in-time.
* **Kickoff schedule knowledge.** Fixture dates/times are treated as known in advance;
  late rescheduling (postponements) is not modelled.
