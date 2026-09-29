# CLAUDE.md - rules for working on this repository

Personal sports analytics & betting **research** engine. Paper mode only.

## Non-negotiables

- Never add code that places real-money bets, talks to bookmaker accounts, or implements
  Martingale / doubling / loss-chasing staking.
- Models read only a `PITSnapshot` (`sports_engine/pit/store.py`). Never pass the
  `HistoricalStore`, the database, or outcome columns to a model or feature.
- Every odds record needs a truthful `available_at`; closing odds become visible at kickoff.
- `data/` is never committed. Test fixtures contain invented rows only.
- football-data.co.uk: opt-in, user-run, private non-commercial use; its robots.txt blocks AI
  agents - do not bulk-download it from an AI session.
- Don't fabricate data, odds, injuries, lineups, sources or results. Unknown -> "UNKNOWN".
- Never tune on the final holdout (`holdout.start_date`); every experiment is registered.
- Promotion requires all gates in `models/champion.py` (leakage suite included); never ROI.
- Numbers in docs come from commands/reports, not memory.

## Commands

```
.venv/bin/python -m pytest -q                                  # full suite
.venv/bin/python -m pytest -q tests/test_temporal_leakage.py tests/test_feature_leakage.py \
    tests/test_point_in_time.py tests/test_future_information.py   # leakage suite (blocks promotion)
.venv/bin/python -m sports_engine --help
```

## Style

Match the surrounding code: dataclasses, type hints, short docstrings explaining *why*,
UTC everywhere, deterministic seeds, JSON (never pickle) for persisted artefacts.
