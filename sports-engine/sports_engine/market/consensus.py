"""Market consensus, best prices, dispersion and stale-price detection.

Consensus methodology (documented in docs/MARKET_ENGINE.md):

1. use individual bookmakers only (aggregate columns such as Max/Avg are
   excluded when individual books exist, to avoid double counting);
2. remove each book's margin with the configured method;
3. consensus = per-selection *median* of fair probabilities, renormalised;
   the trimmed mean and a sharp-book reference (pinnacle / betfair exchange,
   where legitimately available in the data) are reported alongside;
4. dispersion = std of fair probabilities across books (market uncertainty).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import trim_mean

from sports_engine.core.enums import Freshness
from sports_engine.market.margin import remove_margin

SHARP_BOOKS = ("pinnacle", "betfair_exchange")
SELECTIONS = {"1X2": ("H", "D", "A"), "OU": ("OVER", "UNDER"), "AH": ("AH_HOME", "AH_AWAY"), "BTTS": ("YES", "NO")}


@dataclass
class MarketView:
    match_id: str
    market: str
    line: float | None
    selections: tuple[str, ...]
    consensus: np.ndarray | None
    trimmed_mean: np.ndarray | None
    sharp: np.ndarray | None
    sharp_book: str | None
    dispersion: np.ndarray | None
    best_odds: np.ndarray | None
    best_book: list[str] | None
    n_books: int
    newest_at: pd.Timestamp | None
    oldest_at: pd.Timestamp | None
    margin_median: float | None
    method: str
    flags: list[str] = field(default_factory=list)
    per_book: dict[str, np.ndarray] = field(default_factory=dict)

    def prob(self, selection: str) -> float | None:
        if self.consensus is None:
            return None
        return float(self.consensus[self.selections.index(selection)])

    def best(self, selection: str) -> tuple[float | None, str | None]:
        if self.best_odds is None:
            return None, None
        i = self.selections.index(selection)
        return float(self.best_odds[i]), self.best_book[i]


def market_view(odds: pd.DataFrame, match_id: str, market: str = "1X2", line: float | None = None,
                method: str = "power", as_of: datetime | None = None,
                max_staleness_hours: float = 72.0, outlier_threshold: float = 0.06) -> MarketView:
    """Build the market view for one match/market from *visible* latest snapshots."""
    sels = SELECTIONS[market]
    empty = MarketView(match_id, market, line, sels, None, None, None, None, None, None, None, 0, None, None, None, method,
                       ["NO_ODDS"])
    if odds is None or len(odds) == 0:
        return empty
    mids = odds["match_id"].to_numpy()
    mask = (mids == match_id) & (odds["market"].to_numpy() == market)
    if line is not None:
        mask &= np.isclose(odds["line"].to_numpy(dtype=float), line)
    if not mask.any():
        return empty
    books = odds["bookmaker"].to_numpy()[mask]
    selections = odds["selection"].to_numpy()[mask]
    prices_all = odds["odds"].to_numpy(dtype=float)[mask]
    t_all = pd.to_datetime(odds["available_at"], utc=True).dt.tz_convert(None).to_numpy()[mask]  # naive UTC
    agg = odds["is_aggregate"].to_numpy()[mask] if "is_aggregate" in odds.columns else np.zeros(mask.sum(), dtype=int)
    if (agg == 0).any():
        keep = agg == 0
        books, selections, prices_all, t_all = books[keep], selections[keep], prices_all[keep], t_all[keep]
    latest: dict[tuple[str, str], tuple] = {}
    for b, s_, pr, t in zip(books, selections, prices_all, t_all):
        cur = latest.get((b, s_))
        if cur is None or t >= cur[0]:
            latest[(b, s_)] = (t, pr)
    per_book: dict[str, np.ndarray] = {}
    book_odds: dict[str, np.ndarray] = {}
    margins = []
    times = []
    for b in sorted({k[0] for k in latest}):
        if not all((b, s_) in latest for s_ in sels):
            continue
        prices = np.array([latest[(b, s_)][1] for s_ in sels], dtype=float)
        try:
            fp = remove_margin(prices, method)
        except ValueError:
            continue
        per_book[b] = fp.fair
        book_odds[b] = prices
        margins.append(fp.margin)
        times.extend(pd.Timestamp(latest[(b, s_)][0]).tz_localize("UTC") for s_ in sels)
    if not per_book:
        empty.flags = ["INCOMPLETE_MARKET"]
        return empty
    mat = np.vstack(list(per_book.values()))
    cons = np.median(mat, axis=0)
    cons = cons / cons.sum()
    tm = trim_mean(mat, 0.1, axis=0) if len(mat) >= 5 else mat.mean(axis=0)
    tm = tm / tm.sum()
    sharp = sharp_book = None
    for b in SHARP_BOOKS:
        if b in per_book:
            sharp, sharp_book = per_book[b], b
            break
    prices = np.vstack(list(book_odds.values()))
    best_idx = prices.argmax(axis=0)
    books = list(book_odds.keys())
    flags = []
    newest, oldest = max(times), min(times)
    if as_of is not None:
        age_h = (pd.Timestamp(as_of) - newest).total_seconds() / 3600.0
        if age_h > max_staleness_hours:
            flags.append("STALE_ODDS")
    if len(per_book) == 1:
        flags.append("SINGLE_BOOK")
    disp = mat.std(axis=0) if len(mat) > 1 else None
    # a best price whose book is far from consensus is suspicious (stale / erroneous quote)
    for j, s in enumerate(sels):
        b = books[best_idx[j]]
        if len(per_book) >= 3 and abs(per_book[b][j] - cons[j]) > outlier_threshold:
            flags.append(f"OUTLIER_BEST_PRICE:{s}:{b}")
    return MarketView(
        match_id=match_id, market=market, line=line, selections=sels, consensus=cons, trimmed_mean=tm,
        sharp=sharp, sharp_book=sharp_book, dispersion=disp, best_odds=prices.max(axis=0),
        best_book=[books[i] for i in best_idx], n_books=len(per_book), newest_at=newest, oldest_at=oldest,
        margin_median=float(np.median(margins)), method=method, flags=flags, per_book=per_book,
    )


def odds_freshness(newest_at: pd.Timestamp | None, as_of: datetime, fresh_h: float = 6, stale_h: float = 72) -> Freshness:
    if newest_at is None:
        return Freshness.UNKNOWN
    age = (pd.Timestamp(as_of) - newest_at).total_seconds() / 3600.0
    return Freshness.FRESH if age <= fresh_h else (Freshness.AGING if age <= stale_h else Freshness.STALE)


def odds_movement(odds: pd.DataFrame, match_id: str, market: str, selection: str) -> dict:
    """Opening/current/min/max and movement for one selection across all visible snapshots."""
    o = odds[(odds["match_id"] == match_id) & (odds["market"] == market) & (odds["selection"] == selection)]
    if o.empty:
        return {}
    o = o.sort_values("available_at")
    first, last = o.iloc[0], o.iloc[-1]
    hours = max(1e-9, (pd.Timestamp(last["available_at"]) - pd.Timestamp(first["available_at"])).total_seconds() / 3600)
    return {
        "opening": float(first["odds"]), "current": float(last["odds"]),
        "min": float(o["odds"].min()), "max": float(o["odds"].max()),
        "median": float(o["odds"].median()), "n_snapshots": int(len(o)),
        "movement": float(last["odds"] / first["odds"] - 1.0),
        "movement_per_hour": float((last["odds"] / first["odds"] - 1.0) / hours) if len(o) > 1 else 0.0,
    }
