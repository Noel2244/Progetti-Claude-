"""Point-in-time audit of the canonical database.

Checks that the timestamps which the as_of() layer relies on are coherent:

* every finished match has ``result_available_at`` and it is after kickoff/start of day;
* no result is available in the future relative to now;
* no PRE_MATCH / OPENING odds become available at or after kickoff;
* CLOSING odds are never available before kickoff;
* reports the share of approximate / date-only timestamps (what realism the
  backtests can claim).
"""

from __future__ import annotations

import pandas as pd

from sports_engine.core.timeutils import iso, utcnow
from sports_engine.database.db import Database


def pit_audit(db: Database) -> dict:
    now = iso(utcnow())
    q = db.scalar
    checks = []

    def check(name: str, n: int, severity: str, detail: str) -> None:
        checks.append({"check": name, "violations": int(n or 0), "severity": severity, "pass": not n, "detail": detail})

    check("finished_without_availability", q("SELECT COUNT(*) FROM match WHERE status='FINISHED' AND result_available_at IS NULL"),
          "ERROR", "finished matches must carry result_available_at")
    check("result_available_before_kickoff",
          q("SELECT COUNT(*) FROM match WHERE kickoff_utc IS NOT NULL AND result_available_at IS NOT NULL AND result_available_at <= kickoff_utc"),
          "ERROR", "a result cannot be known before kickoff")
    check("result_available_in_future", q("SELECT COUNT(*) FROM match WHERE result_available_at > ?", (now,)),
          "ERROR", "result_available_at later than now")
    check("prematch_odds_at_or_after_kickoff",
          q("""SELECT COUNT(*) FROM odds_snapshot o JOIN match m ON m.match_id=o.match_id
               WHERE o.snapshot_type IN ('PRE_MATCH','OPENING') AND m.kickoff_utc IS NOT NULL AND o.available_at >= m.kickoff_utc"""),
          "ERROR", "pre-match odds must be available before kickoff")
    check("closing_odds_before_kickoff",
          q("""SELECT COUNT(*) FROM odds_snapshot o JOIN match m ON m.match_id=o.match_id
               WHERE o.snapshot_type='CLOSING' AND m.kickoff_utc IS NOT NULL AND o.available_at < m.kickoff_utc"""),
          "ERROR", "closing odds must not be visible before kickoff")
    check("odds_without_timestamp", q("SELECT COUNT(*) FROM odds_snapshot WHERE available_at IS NULL OR available_at=''"),
          "ERROR", "odds without availability time cannot be used point-in-time")
    ts = db.df("SELECT timestamp_quality, COUNT(*) n FROM match GROUP BY 1")
    ots = db.df("SELECT snapshot_type, timestamp_quality, COUNT(*) n FROM odds_snapshot GROUP BY 1,2")
    by_season = db.df("""SELECT competition_id, season, SUM(kickoff_time_known) exact, COUNT(*) n FROM match
                         GROUP BY 1,2 ORDER BY 1,2""")
    by_season["exact_share"] = (by_season["exact"] / by_season["n"]).round(3)
    return {
        "generated_at": now,
        "checks": checks,
        "passed": all(c["pass"] for c in checks if c["severity"] == "ERROR"),
        "match_timestamp_quality": dict(zip(ts["timestamp_quality"], ts["n"].astype(int))) if len(ts) else {},
        "odds_timestamp_quality": ots.to_dict("records"),
        "seasons_date_only": by_season[by_season["exact_share"] < 0.5][["competition_id", "season"]].to_dict("records"),
        "seasons_exact": by_season[by_season["exact_share"] >= 0.5][["competition_id", "season"]].to_dict("records"),
        "realism": ("Backtests over DATE_ONLY seasons decide at 00:00 local on match day and use only results of "
                    "earlier days; APPROXIMATE odds timestamps come from a documented collection schedule, not a "
                    "recorded time - results using them are labelled approximate point-in-time."),
    }
