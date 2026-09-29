"""SQLite access (stdlib ``sqlite3``); DuckDB can attach the same file for analytics."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

import pandas as pd

from sports_engine import SCHEMA_VERSION
from sports_engine.core.timeutils import iso, utcnow

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.migrate()

    def migrate(self) -> None:
        self.conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        self.conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, tuple(params))

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        self.conn.executemany(sql, rows)

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def df(self, sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
        cur = self.conn.execute(sql, tuple(params))
        cols = [c[0] for c in cur.description] if cur.description else []
        return pd.DataFrame(cur.fetchall(), columns=cols)

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return None if row is None else row[0]

    def log_provider_status(self, provider: str, status: str, message: str = "") -> None:
        self.execute(
            "INSERT OR REPLACE INTO provider_status(provider, checked_at, status, message) VALUES (?,?,?,?)",
            (provider, iso(utcnow()), status, message[:2000]),
        )


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
