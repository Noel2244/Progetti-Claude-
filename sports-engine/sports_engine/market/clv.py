"""Closing Line Value.

* ``clv_price`` = odds_taken / closing_odds - 1           (same selection, same or consensus book)
* ``clv_fair``  = odds_taken * p_close_fair - 1            (EV of the bet at the fair closing probability)

Positive values mean the price beat the close. CLV measures *decision* quality
and is available long before profit/loss becomes statistically meaningful.
"""

from __future__ import annotations


def clv_price(odds_taken: float, closing_odds: float) -> float:
    if odds_taken <= 1 or closing_odds <= 1:
        raise ValueError("decimal odds must be > 1")
    return odds_taken / closing_odds - 1.0


def clv_fair(odds_taken: float, closing_fair_prob: float) -> float:
    if not 0 < closing_fair_prob < 1:
        raise ValueError("probability must be in (0, 1)")
    return odds_taken * closing_fair_prob - 1.0
