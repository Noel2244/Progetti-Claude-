"""Content hashing used for provenance, caching and reproducibility."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_CHUNK = 1 << 20


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _default(o: Any) -> Any:
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "tolist"):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    return str(o)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default, ensure_ascii=False)


def stable_hash(obj: Any, length: int = 64) -> str:
    """Deterministic hash of a JSON-serialisable object (dict key order irrelevant)."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:length]


def short_id(prefix: str, *parts: Any, length: int = 16) -> str:
    return f"{prefix}_{stable_hash(list(parts), length)}"
