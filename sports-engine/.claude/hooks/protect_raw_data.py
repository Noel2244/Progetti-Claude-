#!/usr/bin/env python3
"""PreToolUse hook: block edits/writes to the immutable raw lake and manifests."""
import json
import sys

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)
path = str((data.get("tool_input") or {}).get("file_path", "")).replace("\\", "/")
if "/data/raw/" in path or "/data/manifests/" in path:
    print("Blocked: data/raw and data/manifests are immutable (content-addressed raw lake). "
          "Add new data through the acquisition pipeline or data/inbox instead.", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
