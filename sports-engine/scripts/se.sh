#!/usr/bin/env bash
# POSIX wrapper: ./scripts/se.sh <command> [args]   e.g. ./scripts/se.sh daily
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || { echo "run: python3 -m venv .venv && .venv/bin/pip install -e '.[api,analytics,dev]'"; exit 1; }
exec "$PY" -m sports_engine "$@"
