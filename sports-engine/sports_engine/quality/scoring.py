"""DATA_QUALITY_SCORE - transparent, component-based.

The composite score is a weighted mean of the *measurable* components. It is
always reported together with every component and the weakest one, because an
aggregate must never hide a poor component (directive section 11).

Components (all in [0, 1]):

* completeness            finished results / expected fixtures
* consistency             1 - share of structural anomalies (wrong fixture counts,
                          duplicate pairings, past fixtures without result)
* timestamp_quality       mean of EXACT=1, APPROXIMATE=0.7, DATE_ONLY=0.5, UNKNOWN=0
* source_reliability      mean reliability of the best source per match (tier table)
* corroboration           share of matches confirmed by >= 2 independent sources
* agreement               1 - disputed / multi-source matches  (None if unmeasurable)
* odds_coverage           share of matches with pre-match 1X2 odds (market data only)
* freshness               for in-progress seasons: 1 if no overdue results, decays otherwise
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sports_engine.core.enums import Freshness

WEIGHTS = {
    "completeness": 0.25,
    "consistency": 0.20,
    "timestamp_quality": 0.10,
    "source_reliability": 0.15,
    "corroboration": 0.10,
    "agreement": 0.10,
    "freshness": 0.10,
}
# odds_coverage is reported but excluded from the *results* quality composite:
# missing odds is a market-data gap, surfaced separately in the coverage matrix.


@dataclass
class QualityScore:
    score: float
    weakest: str | None
    components: dict[str, float | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"score": round(self.score, 4), "weakest": self.weakest,
                "components": {k: (None if v is None else round(v, 4)) for k, v in self.components.items()},
                "notes": self.notes}


def composite(components: dict[str, float | None], weights: dict[str, float] = WEIGHTS) -> QualityScore:
    used = {k: v for k, v in components.items() if v is not None and k in weights}
    if not used:
        return QualityScore(0.0, None, components, ["no measurable component"])
    total_w = sum(weights[k] for k in used)
    score = sum(weights[k] * v for k, v in used.items()) / total_w
    weakest = min(used, key=lambda k: used[k])
    notes = [f"{k} not measurable" for k, v in components.items() if v is None]
    return QualityScore(score, weakest, components, notes)


def freshness_status(last_updated: datetime | None, now: datetime, fresh: timedelta, stale: timedelta) -> Freshness:
    if last_updated is None:
        return Freshness.UNKNOWN
    age = now - last_updated
    if age <= fresh:
        return Freshness.FRESH
    if age <= stale:
        return Freshness.AGING
    return Freshness.STALE
