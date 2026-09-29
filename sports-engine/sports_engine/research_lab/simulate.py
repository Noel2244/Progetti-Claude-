"""Synthetic league + bookmaker simulator (clearly labelled SYNTHETIC).

Used to validate the machinery end-to-end where the truth is known:

* ``market="efficient"`` - books price the true probabilities (+ noise + margin).
  A sound system must find NO robust edge here.
* ``market="biased"``    - books systematically misprice (e.g. overrate home
  favourites). A sound system should detect it, with positive CLV.
* ``market=None``        - results only.

Never mix synthetic data with real data: match ids are prefixed ``syn_``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from sports_engine.models.score_matrix import DerivedMarkets, score_matrix


def _round_robin(n: int) -> list[list[tuple[int, int]]]:
    teams = list(range(n))
    rounds = []
    for r in range(n - 1):
        pairs = [(teams[i], teams[n - 1 - i]) for i in range(n // 2)]
        if r % 2:
            pairs = [(b, a) for a, b in pairs]
        rounds.append(pairs)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return rounds + [[(b, a) for a, b in rd] for rd in rounds]


def simulate_league(n_teams: int = 20, seasons: int = 6, start_year: int = 2015, seed: int = 0,
                    competition_id: str = "ITA1", tz: str = "Europe/Rome", market: str | None = "efficient",
                    margin: float = 0.05, n_books: int = 4, book_noise: float = 0.03, closing_noise: float = 0.01,
                    home_fav_bias: float = 0.0, mu: float = 0.12, home_adv: float = 0.27, rho: float = -0.08,
                    strength_sd: float = 0.3, season_drift: float = 0.12) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    zone = ZoneInfo(tz)
    att = rng.normal(0, strength_sd, n_teams)
    de = rng.normal(0, strength_sd * 0.8, n_teams)
    teams = [f"syn-team-{i:02d}" for i in range(n_teams)]
    matches, odds = [], []
    truth = {}
    rounds = _round_robin(n_teams)
    for s in range(seasons):
        year = start_year + s
        if s:
            att = att + rng.normal(0, season_drift, n_teams)
            de = de + rng.normal(0, season_drift * 0.8, n_teams)
        first_sat = date(year, 8, 20) + timedelta(days=(5 - date(year, 8, 20).weekday()) % 7)
        for r, pairs in enumerate(rounds):
            day = first_sat + timedelta(days=7 * r + (r // 10) * 7)  # small winter/international breaks
            for k, (h, a) in enumerate(pairs):
                d = day + timedelta(days=1 if k >= len(pairs) // 2 else 0)
                ko_local = datetime.combine(d, time(15 if k % 2 else 18, 0), tzinfo=zone)
                ko = ko_local.astimezone(ZoneInfo("UTC"))
                lh = float(np.exp(mu + home_adv + att[h] - de[a]))
                la = float(np.exp(mu + att[a] - de[h]))
                m, _ = score_matrix(lh, la, rho)
                idx = rng.choice(m.size, p=m.ravel())
                hg, ag = np.unravel_index(idx, m.shape)
                mid = f"syn_{competition_id}_{year}_{r:02d}_{k:02d}"
                p_true = np.array(DerivedMarkets(m).one_x_two())
                truth[mid] = p_true
                matches.append({
                    "match_id": mid, "competition_id": competition_id, "season": f"{year}-{year + 1}",
                    "season_start_year": year, "match_date": d.isoformat(), "kickoff_utc": ko.isoformat(),
                    "kickoff_time_known": 1, "timestamp_quality": "EXACT", "home_team_id": teams[h], "away_team_id": teams[a],
                    "home_goals": int(hg), "away_goals": int(ag), "ht_home_goals": None, "ht_away_goals": None,
                    "status": "FINISHED", "result_available_at": (ko + timedelta(hours=3)).isoformat(), "score_disputed": 0,
                    "stats_json": None,
                })
                if market is None:
                    continue
                p_mkt = p_true.copy()
                if home_fav_bias and p_true[0] > 0.5:
                    p_mkt = p_mkt + np.array([home_fav_bias, -home_fav_bias / 2, -home_fav_bias / 2])
                    p_mkt = np.clip(p_mkt, 0.02, 0.98)
                    p_mkt /= p_mkt.sum()
                for b in range(n_books):
                    for snap, noise, at in (("PRE_MATCH", book_noise, ko - timedelta(hours=26)),
                                            ("CLOSING", closing_noise, ko)):
                        base = p_true if snap == "CLOSING" else p_mkt  # prices converge toward the truth by the close
                        q = np.exp(np.log(base) + rng.normal(0, noise, 3))
                        q /= q.sum()
                        o = 1.0 / (q * (1 + margin))
                        for sel, price in zip("HDA", o):
                            odds.append({"match_id": mid, "source": "synthetic", "bookmaker": f"book{b}", "market": "1X2",
                                         "selection": sel, "line": np.nan, "odds": round(float(price), 3),
                                         "snapshot_type": snap, "available_at": at.isoformat(),
                                         "timestamp_quality": "EXACT", "is_aggregate": 0})
    return pd.DataFrame(matches), pd.DataFrame(odds), truth
