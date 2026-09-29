---
description: Evaluate champion/challenger promotion gates for a backtest run. Args: run_id model reference
---
Run `python -m sports_engine gates --run-id $1 --model ${2:-dixon_coles} --reference ${3:-elo}`.
This executes the leakage test-suite. Explain each gate (pass/fail + detail). Only promote
(`--promote`) if the owner explicitly asks and every required gate passes. Never promote on ROI.
