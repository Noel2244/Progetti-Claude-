---
description: Point-in-time audit + leakage test-suite
---
Run `python -m sports_engine pit-audit` and
`python -m pytest -q tests/test_temporal_leakage.py tests/test_feature_leakage.py tests/test_point_in_time.py tests/test_future_information.py`.
Report every failing check with its evidence. Any failure blocks model promotion.
