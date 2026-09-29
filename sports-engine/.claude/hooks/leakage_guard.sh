#!/usr/bin/env bash
# Stop hook: if point-in-time sensitive code changed, the leakage suite must pass before finishing.
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
changed=$(git status --porcelain -- sports_engine/pit sports_engine/models sports_engine/backtesting sports_engine/features sports_engine/market 2>/dev/null)
[ -z "$changed" ] && exit 0
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python.exe; [ -x "$PY" ] || PY=python3
if ! "$PY" -m pytest -q -x tests/test_temporal_leakage.py tests/test_feature_leakage.py tests/test_point_in_time.py tests/test_future_information.py >/tmp/leakage_guard.log 2>&1; then
  echo "Leakage suite FAILED after changes to point-in-time sensitive code. Fix before finishing:" >&2
  tail -30 /tmp/leakage_guard.log >&2
  exit 2
fi
exit 0
