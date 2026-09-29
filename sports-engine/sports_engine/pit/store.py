"""Point-in-time data access: ``HistoricalStore.as_of(ts) -> PITSnapshot``.

The snapshot answers exactly one question: *what did the system know at ts?*

* results are visible only when ``result_available_at <= ts``;
* fixtures expose schedule information only (goal columns are removed);
* odds are visible only when ``available_at <= ts`` - closing odds are stamped at
  kickoff, so they can never reach a pre-kickoff decision;
* models receive a ``PITSnapshot`` and never the underlying store.

Every snapshot carries a content fingerprint (XOR of per-row hashes over the
visible results) so each prediction can be tied to the exact data it saw.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from sports_engine.core.errors import LeakageError
from sports_engine.core.timeutils import ensure_utc, iso

RESULT_COLUMNS = ["home_goals", "away_goals", "ht_home_goals", "ht_away_goals", "result_available_at", "stats_json"]
FIXTURE_COLUMNS = ["match_id", "competition_id", "season", "season_start_year", "match_date", "kickoff_utc",
                   "kickoff_time_known", "timestamp_quality", "home_team_id", "away_team_id", "status"]


def _row_hashes(keys: pd.Series) -> np.ndarray:
    return np.array([int.from_bytes(hashlib.blake2b(k.encode(), digest_size=8).digest(), "little") for k in keys],
                    dtype=np.uint64)


def _ts(values) -> pd.Series:
    return pd.to_datetime(values, utc=True, format="ISO8601")


class HistoricalStore:
    """Full canonical data in memory. Do NOT pass this object to models."""

    def __init__(self, matches: pd.DataFrame, odds: pd.DataFrame | None = None):
        m = matches.copy()
        for col in ("match_id", "competition_id", "home_team_id", "away_team_id", "season", "status", "match_date"):
            if col in m.columns:   # plain object dtype: hash-based lookups are much faster than Arrow strings
                m[col] = m[col].astype(object)
        m["kickoff_utc"] = _ts(m["kickoff_utc"])
        m["result_available_at"] = _ts(m["result_available_at"])
        self._fixtures = m[[c for c in FIXTURE_COLUMNS if c in m.columns]].copy()
        fin = m[(m["status"] == "FINISHED") & m["result_available_at"].notna()].copy()
        fin = fin.sort_values(["result_available_at", "match_date", "match_id"], kind="mergesort").reset_index(drop=True)
        if "score_disputed" not in fin.columns:
            fin["score_disputed"] = 0
        self._results = fin
        self._result_pos = {mid: i for i, mid in enumerate(fin["match_id"])}   # position in availability order
        self._fixture_pos = {mid: i for i, mid in enumerate(self._fixtures["match_id"])}
        self._competitions = set(m["competition_id"])
        self._avail_ns = fin["result_available_at"].values.astype("datetime64[ns]").astype(np.int64)
        keys = fin["match_id"] + ":" + fin["home_goals"].astype(str) + ":" + fin["away_goals"].astype(str)
        self._cumxor = np.bitwise_xor.accumulate(_row_hashes(keys)) if len(fin) else np.zeros(0, dtype=np.uint64)
        if odds is not None and not odds.empty:
            o = odds.copy()
            o["available_at"] = _ts(o["available_at"])
            o = o.sort_values("available_at", kind="mergesort").reset_index(drop=True)
            self._odds = o
            self._odds_ns = o["available_at"].values.astype("datetime64[ns]").astype(np.int64)
            self._odds_idx = {k: np.asarray(v) for k, v in o.groupby("match_id", sort=False).indices.items()}
        else:
            self._odds = pd.DataFrame(columns=["match_id", "bookmaker", "market", "selection", "line", "odds",
                                               "snapshot_type", "available_at", "timestamp_quality", "source"])
            self._odds_ns = np.zeros(0, dtype=np.int64)
            self._odds_idx = {}

    @classmethod
    def from_db(cls, db, competitions: list[str] | None = None, with_odds: bool = True) -> "HistoricalStore":
        where, params = "", ()
        if competitions:
            where = f"WHERE competition_id IN ({','.join('?' * len(competitions))})"
            params = tuple(competitions)
        matches = db.df(f"SELECT * FROM match {where}", params)
        odds = None
        if with_odds:
            ow = where.replace("competition_id", "m.competition_id")
            odds = db.df(
                f"""SELECT o.match_id, o.source, o.bookmaker, o.market, o.selection, o.line, o.odds, o.snapshot_type,
                           o.available_at, o.timestamp_quality, COALESCE(b.is_aggregate, 0) AS is_aggregate
                    FROM odds_snapshot o JOIN match m ON m.match_id = o.match_id
                    LEFT JOIN bookmaker b ON b.bookmaker_id = o.bookmaker {ow}""",
                params,
            )
        return cls(matches, odds)

    # ------------------------------------------------------------------ access
    def as_of(self, ts: datetime) -> "PITSnapshot":
        ts = ensure_utc(ts)
        t_ns = pd.Timestamp(ts).value
        n = int(np.searchsorted(self._avail_ns, t_ns, side="right"))
        k = int(np.searchsorted(self._odds_ns, t_ns, side="right"))
        fp = int(self._cumxor[n - 1]) if n > 0 else 0
        return PITSnapshot(ts, self._results.iloc[:n], self._odds.iloc[:k], self._fixtures,
                           f"{iso(ts)}|{n}|{fp:016x}", self._odds, self._odds_idx, k,
                           self._result_pos, self._fixture_pos, n, self._competitions)

    def fixtures(self, start: datetime | None = None, end: datetime | None = None,
                 competitions: list[str] | None = None) -> pd.DataFrame:
        """Schedule rows (no results) - used to decide *what* to predict."""
        f = self._fixtures
        if competitions:
            f = f[f["competition_id"].isin(competitions)]
        dates = pd.to_datetime(f["match_date"])
        if start is not None:
            f = f[dates >= pd.Timestamp(start.date())]
            dates = pd.to_datetime(f["match_date"])
        if end is not None:
            f = f[dates <= pd.Timestamp(end.date())]
        return f.copy()

    def outcomes(self, match_ids) -> pd.DataFrame:
        """Evaluation-only access to realised results (never for model input)."""
        return self._results[self._results["match_id"].isin(set(match_ids))][
            ["match_id", "home_goals", "away_goals", "result_available_at", "score_disputed"]]

    def closing_odds(self, match_ids) -> pd.DataFrame:
        """Evaluation-only access to closing prices (CLV)."""
        o = self._odds
        return o[o["match_id"].isin(set(match_ids)) & (o["snapshot_type"] == "CLOSING")]

    def closing_odds_for(self, match_id: str) -> pd.DataFrame:
        """Evaluation-only: closing prices of one match (after the fact, for CLV)."""
        idx = self._odds_idx.get(match_id)
        if idx is None:
            return self._odds.iloc[0:0]
        o = self._odds.iloc[idx]
        return o[o["snapshot_type"] == "CLOSING"]

    @property
    def n_results(self) -> int:
        return len(self._results)


@dataclass(frozen=True)
class PITSnapshot:
    as_of: datetime
    _results: pd.DataFrame
    _odds: pd.DataFrame
    _fixtures: pd.DataFrame
    fingerprint: str
    _odds_all: pd.DataFrame | None = None
    _odds_idx: dict | None = None
    _odds_k: int = 0
    _result_pos: dict | None = None
    _fixture_pos: dict | None = None
    _n_results: int = 0
    _competitions: set | None = None

    def results(self, competitions: list[str] | None = None, since: datetime | None = None,
                exclude_disputed: bool = False) -> pd.DataFrame:
        r = self._results
        if competitions and not (self._competitions is not None and self._competitions <= set(competitions)):
            r = r[r["competition_id"].isin(competitions)]
        if since is not None:
            r = r[r["result_available_at"] >= pd.Timestamp(ensure_utc(since))]
        if exclude_disputed:
            r = r[r["score_disputed"] == 0]
        return r

    def fixtures(self, match_ids) -> pd.DataFrame:
        ids = list(dict.fromkeys(match_ids))
        if self._fixture_pos is not None:
            rows = sorted(self._fixture_pos[m] for m in ids if m in self._fixture_pos)
            f = self._fixtures.iloc[rows]
        else:
            f = self._fixtures[self._fixtures["match_id"].isin(set(ids))]
        f = f[[c for c in f.columns if c not in RESULT_COLUMNS]].copy()
        # the stored status reflects the *final* state; at as_of only visible results count as finished
        if self._result_pos is not None:
            n = self._n_results
            visible = [self._result_pos.get(m, n) < n for m in f["match_id"]]
        else:
            visible = f["match_id"].isin(set(self._results["match_id"])).to_numpy()
        f["status"] = np.where(visible, "FINISHED", "SCHEDULED")
        return f

    def odds(self, match_ids=None, market: str | None = None, include_aggregates: bool = True) -> pd.DataFrame:
        o = self._odds
        if match_ids is not None:
            o = o[o["match_id"].isin(set(match_ids))]
        if market is not None:
            o = o[o["market"] == market]
        if not include_aggregates and "is_aggregate" in o.columns:
            o = o[o["is_aggregate"] == 0]
        return o

    def match_odds(self, match_id: str, market: str | None = None) -> pd.DataFrame:
        """Visible odds of one match (fast path via the per-match index)."""
        if self._odds_idx is None:
            return self.odds([match_id], market)
        idx = self._odds_idx.get(match_id)
        if idx is None:
            return self._odds.iloc[0:0]
        idx = idx[idx < self._odds_k]      # rows are sorted by available_at: position < k  <=>  visible
        o = self._odds_all.iloc[idx]
        return o if market is None else o[o["market"] == market]

    def latest_odds(self, match_ids=None, market: str | None = None) -> pd.DataFrame:
        """Most recent visible snapshot per (match, bookmaker, market, selection, line)."""
        o = self.odds(match_ids, market)
        if o.empty:
            return o
        keys = ["match_id", "bookmaker", "market", "selection", "line"]
        o = o.assign(line=o["line"].fillna(-9999.0))
        latest = o.sort_values("available_at").groupby(keys, as_index=False, dropna=False).tail(1)
        return latest.assign(line=latest["line"].replace(-9999.0, np.nan))

    def assert_no_future(self, df: pd.DataFrame, column: str) -> None:
        if df is None or df.empty or column not in df.columns:
            return
        mx = pd.to_datetime(df[column], utc=True).max()
        if pd.notna(mx) and mx > pd.Timestamp(self.as_of):
            raise LeakageError(f"{column} max {mx} is after as_of {self.as_of}")
