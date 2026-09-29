"""Prediction timing: every prediction records all of its cutoffs.

MATCH_TIME, DATA_CUTOFF_TIME, FEATURE_CUTOFF_TIME, ODDS_CUTOFF_TIME,
LINEUP_CUTOFF_TIME and MODEL_RUN_TIME (directive section 18).

Decision-time policy (backtests)
--------------------------------
A bet can only be struck at a price that exists *at decision time*. Deciding on
Saturday using Friday's price while also using Saturday's results would book a
price that may no longer exist (stale-price optimism). Therefore:

* if pre-match odds exist, decision time = the latest pre-match snapshot that is
  at least ``lead`` before kickoff; features are cut at the same instant;
* else, with an exact kickoff: decision time = kickoff - lead;
* else (date-only): decision time = 00:00 local on match day.

The decision time is always <= kickoff and all cutoffs are <= decision time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from sports_engine.core.errors import LeakageError
from sports_engine.core.timeutils import ensure_utc, iso, start_of_local_day_utc


@dataclass(frozen=True)
class Cutoffs:
    match_time: datetime | None           # exact kickoff (None when only the date is known)
    prediction_timestamp: datetime
    data_cutoff: datetime
    feature_cutoff: datetime
    odds_cutoff: datetime
    lineup_cutoff: datetime | None
    model_run_time: datetime
    policy: str

    def validate(self) -> None:
        for name in ("data_cutoff", "feature_cutoff", "odds_cutoff"):
            if getattr(self, name) > self.prediction_timestamp:
                raise LeakageError(f"{name} after prediction timestamp")
        if self.match_time is not None and self.prediction_timestamp > self.match_time:
            raise LeakageError("prediction timestamp after kickoff")

    def as_dict(self) -> dict:
        return {k: (iso(v) if isinstance(v, datetime) else v) for k, v in asdict(self).items()}


class DecisionTimingPolicy:
    def __init__(self, lead_minutes: int = 60):
        self.lead = timedelta(minutes=lead_minutes)

    def cutoffs(self, kickoff: datetime | None, match_date: date, timezone: str,
                prematch_odds_times: list[datetime] | None = None, model_run_time: datetime | None = None) -> Cutoffs:
        if kickoff is not None:
            latest_allowed = ensure_utc(kickoff) - self.lead
        else:
            latest_allowed = start_of_local_day_utc(match_date, timezone) + timedelta(hours=12)
        usable = sorted(t for t in (prematch_odds_times or []) if t is not None and ensure_utc(t) <= latest_allowed)
        if usable:
            t = ensure_utc(usable[-1])
            policy = "at_latest_prematch_odds"
        elif kickoff is not None:
            t = latest_allowed
            policy = "kickoff_minus_lead"
        else:
            t = start_of_local_day_utc(match_date, timezone)
            policy = "start_of_match_day"
        c = Cutoffs(
            match_time=ensure_utc(kickoff) if kickoff is not None else None,
            prediction_timestamp=t,
            data_cutoff=t,
            feature_cutoff=t,
            odds_cutoff=t,
            lineup_cutoff=None,   # no lineup source integrated yet -> lineup uncertainty HIGH
            model_run_time=model_run_time or t,
            policy=policy,
        )
        c.validate()
        return c


def kickoff_or_none(value) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    return ts.to_pydatetime() if ts.tzinfo else ts.tz_localize("UTC").to_pydatetime()
