---
description: Walk-forward backtest with honest interpretation. Args: competitions start end (e.g. ITA1 1995-07-01 2025-06-30)
---
Run `python -m sports_engine backtest --competitions $1 --start $2 --end $3` (defaults ITA1,
1995-07-01, 2025-06-30 if not given). Then read reports/backtests/<run_id>/report.md and report:
probability quality vs climatology/Elo/market with CIs, calibration effect, per-season stability,
betting simulation only if odds existed, and the multiple-testing warning. Do not claim an edge
unless the CI excludes zero and CLV supports it.
