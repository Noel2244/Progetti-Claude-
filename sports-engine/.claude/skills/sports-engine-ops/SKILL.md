---
name: sports-engine-ops
description: How to operate the personal sports research engine safely - commands, invariants and red lines. Use whenever running, extending or explaining this project.
---
# Operating the engine

Commands: `python -m sports_engine <audit-env|sources|download-history|import-inbox|ingest|validate-data|coverage|pit-audit|backtest|gates|paper run|paper reconcile|paper status|paper verify|daily|report|experiments|models|journal|simulate|serve>`.
Windows wrappers live in scripts/*.ps1.

Invariants you must preserve:
1. Paper mode only. No code path may place real bets. No Martingale / progression staking.
2. Models see `PITSnapshot` only. Every timestamp is UTC; results visible at `result_available_at`; closing odds at kickoff.
3. Raw data immutable (data/raw, manifests); nothing in data/ is ever committed.
4. football-data.co.uk is opt-in and user-run (private, non-commercial; robots.txt blocks AI agents) - AI sessions must not bulk-download it.
5. Every NO BET carries reasons; "no edge" is a valid answer.
6. Promotion needs all gates incl. the leakage suite; never on ROI; final holdout access is logged.
7. Numbers in docs come from commands/reports, never from memory.
