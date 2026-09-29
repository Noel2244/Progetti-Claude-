"""Immutable, content-addressed raw data lake.

Layout::

    data/raw/<provider>/<dataset_key>/<sha256>.<ext>     (read-only after write)
    data/manifests/<provider>.jsonl                      (append-only provenance log)

Rules
-----
* Raw files are never overwritten. A changed upstream file (e.g. a current-season
  CSV) produces a *new* content hash and a new file; old revisions are kept, which
  also lets us measure source revision behaviour.
* Every stored file has a manifest entry with source URL, timestamps, hash,
  license and terms reference.
"""

from __future__ import annotations

import json
import os
import re
import stat
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from sports_engine.core.errors import ImmutableRecordError
from sports_engine.core.hashing import sha256_bytes, sha256_file
from sports_engine.core.timeutils import iso, utcnow

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]*$")
_SAFE_EXT = re.compile(r"^[a-z0-9]{1,8}$")


def safe_key(key: str) -> str:
    """Validate a dataset key; rejects traversal and odd characters."""
    if not key or not _SAFE_KEY.match(key) or ".." in key.split("/") or key.startswith("/"):
        raise ValueError(f"unsafe dataset key: {key!r}")
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise ValueError(f"unsafe dataset key: {key!r}")
    return key


@dataclass
class ManifestEntry:
    provider: str
    dataset_key: str
    sha256: str
    size_bytes: int
    stored_path: str               # relative to the lake root
    url: str | None
    downloaded_at: str
    source_last_modified: str | None = None
    etag: str | None = None
    content_type: str | None = None
    license_id: str | None = None
    terms_ref: str | None = None
    acquisition: str = "download"  # download | manual_import
    notes: str | None = None
    extra: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)


class RawDataLake:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw"
        self.manifest_dir = self.data_dir / "manifests"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ storage
    def _target(self, provider: str, dataset_key: str, digest: str, ext: str) -> Path:
        safe_key(provider)
        safe_key(dataset_key)
        if not _SAFE_EXT.match(ext):
            raise ValueError(f"unsafe extension: {ext!r}")
        target = (self.raw_dir / provider / dataset_key / f"{digest}.{ext}").resolve()
        if self.raw_dir.resolve() not in target.parents:
            raise ValueError("path traversal detected")
        return target

    def store_bytes(self, provider: str, dataset_key: str, content: bytes, ext: str, **meta) -> ManifestEntry:
        digest = sha256_bytes(content)
        target = self._target(provider, dataset_key, digest, ext)
        with self._lock:
            if target.exists():
                if sha256_file(target) != digest:
                    raise ImmutableRecordError(f"raw file corrupted or tampered: {target}")
                existing = self.find(provider, dataset_key, digest)
                if existing is not None:
                    return existing
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(target.suffix + ".tmp")
                with open(tmp, "wb") as fh:
                    fh.write(content)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, target)
                os.chmod(target, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
            entry = ManifestEntry(
                provider=provider,
                dataset_key=dataset_key,
                sha256=digest,
                size_bytes=len(content),
                stored_path=str(target.relative_to(self.data_dir.resolve())).replace(os.sep, "/"),
                url=meta.pop("url", None),
                downloaded_at=meta.pop("downloaded_at", None) or iso(utcnow()),
                **meta,
            )
            with open(self.manifest_dir / f"{provider}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(entry.to_json() + "\n")
            return entry

    def store_file(self, provider: str, dataset_key: str, src: str | Path, ext: str | None = None, **meta) -> ManifestEntry:
        src = Path(src)
        ext = ext or src.suffix.lstrip(".").lower() or "bin"
        return self.store_bytes(provider, dataset_key, src.read_bytes(), ext, **meta)

    # ------------------------------------------------------------------ manifest
    def entries(self, provider: str | None = None) -> list[ManifestEntry]:
        files: Iterable[Path]
        if provider:
            files = [self.manifest_dir / f"{safe_key(provider)}.jsonl"]
        else:
            files = sorted(self.manifest_dir.glob("*.jsonl"))
        out: list[ManifestEntry] = []
        for f in files:
            if not f.exists():
                continue
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(ManifestEntry(**json.loads(line)))
        return out

    def history(self, provider: str, dataset_key: str) -> list[ManifestEntry]:
        return sorted(
            (e for e in self.entries(provider) if e.dataset_key == dataset_key),
            key=lambda e: e.downloaded_at,
        )

    def latest(self, provider: str, dataset_key: str) -> ManifestEntry | None:
        hist = self.history(provider, dataset_key)
        return hist[-1] if hist else None

    def latest_by_key(self, provider: str) -> dict[str, ManifestEntry]:
        latest: dict[str, ManifestEntry] = {}
        for e in sorted(self.entries(provider), key=lambda e: e.downloaded_at):
            latest[e.dataset_key] = e
        return latest

    def find(self, provider: str, dataset_key: str, digest: str) -> ManifestEntry | None:
        for e in self.history(provider, dataset_key):
            if e.sha256 == digest:
                return e
        return None

    def read(self, entry: ManifestEntry, verify: bool = True) -> bytes:
        path = self.data_dir / entry.stored_path
        data = path.read_bytes()
        if verify and sha256_bytes(data) != entry.sha256:
            raise ImmutableRecordError(f"hash mismatch for {path}")
        return data

    def verify(self) -> list[str]:
        """Integrity audit: returns a list of problems (empty == healthy)."""
        problems = []
        for e in self.entries():
            p = self.data_dir / e.stored_path
            if not p.exists():
                problems.append(f"missing file: {e.stored_path}")
            elif sha256_file(p) != e.sha256:
                problems.append(f"hash mismatch: {e.stored_path}")
        return problems
