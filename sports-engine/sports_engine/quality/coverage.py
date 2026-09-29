"""Coverage matrix, data-gaps report, per-season quality and the historical data report."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

import pandas as pd

from sports_engine.core.enums import SOURCE_TIER_RELIABILITY, TIMESTAMP_QUALITY_SCORE, TimestampQuality
from sports_engine.core.timeutils import iso, utcnow
from sports_engine.database.db import Database, dumps
from sports_engine.entity.competitions import load_competitions, season_label
from sports_engine.providers.registry import PROVIDER_CLASSES
from sports_engine.quality.scoring import composite

INTERRUPTIONS = {"ITA1": {1943: "not played (WWII)", 1944: "not played (WWII)"}}

NOT_AVAILABLE = "0"  # explicit: the field is not provided by any integrated source


def _source_reliability() -> dict[str, float]:
    return {name: SOURCE_TIER_RELIABILITY[cls.info.source_tier] for name, cls in PROVIDER_CLASSES.items()}


def coverage_matrix(db: Database) -> pd.DataFrame:
    m = db.df("""SELECT match_id, competition_id, season, season_start_year, status, timestamp_quality,
                        home_team_id, away_team_id, sources, n_sources, score_disputed, stats_json, match_date
                 FROM match""")
    if m.empty:
        return pd.DataFrame()
    odds = db.df("""SELECT o.match_id, o.bookmaker, o.market, o.snapshot_type, o.timestamp_quality, b.is_aggregate
                    FROM odds_snapshot o LEFT JOIN bookmaker b ON b.bookmaker_id = o.bookmaker""")
    managers = db.df("""SELECT match_id FROM source_match WHERE extra_json LIKE '%managers%' AND match_id IS NOT NULL""")
    rel = _source_reliability()
    rows = []
    today = date.today()
    for (cid, sy), g in m.groupby(["competition_id", "season_start_year"]):
        teams = set(g.home_team_id) | set(g.away_team_id)
        n_teams = len(teams)
        comp = load_competitions()[cid]
        expected = n_teams * (n_teams - 1) if not comp.is_cup else len(g)
        finished = int((g.status == "FINISHED").sum())
        scheduled = int((g.status == "SCHEDULED").sum())
        unknown = int((g.status == "UNKNOWN").sum())
        ids = set(g.match_id)
        og = odds[odds.match_id.isin(ids)] if not odds.empty else odds
        def share(mask_ids: set) -> float:
            return round(len(mask_ids & ids) / max(1, len(ids)), 4)
        pre = set(og[(og.market == "1X2") & (og.snapshot_type == "PRE_MATCH")].match_id) if not og.empty else set()
        opening = set(og[og.snapshot_type == "OPENING"].match_id) if not og.empty else set()
        closing = set(og[(og.market == "1X2") & (og.snapshot_type == "CLOSING")].match_id) if not og.empty else set()
        ou = set(og[og.market == "OU"].match_id) if not og.empty else set()
        ah = set(og[og.market == "AH"].match_id) if not og.empty else set()
        books = sorted(set(og[og.is_aggregate == 0].bookmaker)) if not og.empty else []
        stats = [json.loads(s) if s else {} for s in g.stats_json]
        def stat_share(key: str) -> float:
            return round(sum(1 for s in stats if key in s) / max(1, len(g)), 4)
        xg_share = round(sum(1 for s in stats if "by_team" in s) / max(1, len(g)), 4)
        ts = g.timestamp_quality.value_counts(normalize=True).to_dict()
        exact_share = round(ts.get(TimestampQuality.EXACT.value, 0.0), 4)
        pit = []
        pit.append("RESULTS_PIT_EXACT" if exact_share >= 0.95 else "RESULTS_PIT_DAILY")
        if pre:
            odds_tq = set(og[og.snapshot_type == "PRE_MATCH"].timestamp_quality)
            pit.append("ODDS_PIT_EXACT" if odds_tq == {"EXACT"} else "ODDS_PIT_APPROXIMATE")
        else:
            pit.append("NO_ODDS")
        season_over = scheduled == 0 and date.fromisoformat(g.match_date.max()) < today
        rows.append({
            "competition": cid,
            "season": season_label(int(sy), comp.season_style),
            "state": "COMPLETE" if season_over else "IN_PROGRESS",
            "teams": n_teams,
            "matches": len(g),
            "expected_matches": expected,
            "results": finished,
            "results_pct": round(finished / max(1, expected), 4),
            "past_without_result": unknown,
            "odds_1x2_prematch_pct": share(pre),
            "opening_odds_pct": share(opening),
            "closing_odds_pct": share(closing),
            "ou_odds_pct": share(ou),
            "ah_odds_pct": share(ah),
            "bookmakers": len(books),
            "events_pct": xg_share,
            "xg_pct": xg_share,
            "lineups_pct": 0.0,
            "players_pct": 0.0,
            "injuries_pct": 0.0,
            "cards_pct": stat_share("home_yellow"),
            "corners_pct": stat_share("home_corners"),
            "shots_pct": stat_share("home_shots"),
            "possession_pct": 0.0,
            "managers_pct": share(set(managers.match_id)) if not managers.empty else 0.0,
            "formations_pct": 0.0,
            "exact_kickoff_pct": exact_share,
            "multi_source_pct": round(float((g.n_sources >= 2).mean()), 4),
            "disputed_scores": int(g.score_disputed.sum()),
            "sources": ",".join(sorted({s for js in g.sources for s in json.loads(js)})),
            "pit_capability": "+".join(pit),
            "source_reliability": round(float(g.sources.map(lambda js: max(rel.get(s, 0.1) for s in json.loads(js))).mean()), 4),
            "timestamp_score": round(float(g.timestamp_quality.map(lambda t: TIMESTAMP_QUALITY_SCORE[TimestampQuality(t)]).mean()), 4),
        })
    return pd.DataFrame(rows).sort_values(["competition", "season"]).reset_index(drop=True)


def season_quality(row: dict, dup_pairings: int = 0, wrong_counts: int = 0) -> dict:
    n = max(1, row["matches"])
    multi = row["multi_source_pct"]
    comps = {
        "completeness": min(1.0, row["results"] / max(1, row["expected_matches"])) if row["state"] == "COMPLETE"
        else min(1.0, row["results"] / max(1, row["results"] + row["past_without_result"])),
        "consistency": max(0.0, 1.0 - (dup_pairings + wrong_counts + row["past_without_result"]) / n),
        "timestamp_quality": row["timestamp_score"],
        "source_reliability": row["source_reliability"],
        "corroboration": multi,
        "agreement": (1.0 - row["disputed_scores"] / (multi * n)) if multi > 0 else None,
        "freshness": 1.0 if row["past_without_result"] == 0 else max(0.0, 1.0 - row["past_without_result"] / 10.0),
        "odds_coverage": row["odds_1x2_prematch_pct"],
    }
    return composite(comps).as_dict()


def structural_anomalies(db: Database, competition_id: str, season_start_year: int) -> tuple[int, int]:
    g = db.df("SELECT home_team_id, away_team_id, status FROM match WHERE competition_id=? AND season_start_year=?",
              (competition_id, season_start_year))
    if g.empty:
        return 0, 0
    dup = int(g.duplicated(["home_team_id", "away_team_id"]).sum())
    teams = set(g.home_team_id) | set(g.away_team_id)
    per_team = defaultdict(int)
    for r in g.itertuples():
        per_team[r.home_team_id] += 1
        per_team[r.away_team_id] += 1
    expected = 2 * (len(teams) - 1)
    wrong = sum(1 for t in teams if per_team[t] != expected)
    return dup, wrong


def gaps_report(db: Database, cov: pd.DataFrame | None = None) -> dict:
    cov = coverage_matrix(db) if cov is None else cov
    out: dict = {"generated_at": iso(utcnow()), "competitions": {}}
    if cov.empty:
        return out
    for cid, g in cov.groupby("competition"):
        years = sorted(int(s[:4]) for s in g.season)
        present = set(years)
        missing = [y for y in range(years[0], years[-1] + 1) if y not in present]
        interruptions = INTERRUPTIONS.get(cid, {})
        incomplete = []
        for r in g.to_dict("records"):
            dup, wrong = structural_anomalies(db, cid, int(r["season"][:4]))
            if r["state"] == "COMPLETE" and (r["results"] < r["expected_matches"] or dup or wrong):
                incomplete.append({"season": r["season"], "results": r["results"], "expected": r["expected_matches"],
                                   "duplicate_pairings": dup, "teams_with_wrong_fixture_count": wrong})
        out["competitions"][cid] = {
            "oldest_season": g.season.iloc[0],
            "newest_season": g.season.iloc[-1],
            "seasons_present": len(g),
            "missing_seasons": [{"season": season_label(y), "note": interruptions.get(y, "no source provides it")} for y in missing],
            "incomplete_seasons": incomplete,
            "seasons_with_past_fixtures_missing_results": g[g.past_without_result > 0][["season", "past_without_result"]].to_dict("records"),
            "seasons_without_prematch_odds": int((g.odds_1x2_prematch_pct == 0).sum()),
            "seasons_without_closing_odds": int((g.closing_odds_pct == 0).sum()),
            "seasons_without_exact_kickoff": int((g.exact_kickoff_pct < 0.5).sum()),
            "seasons_with_xg": g[g.xg_pct > 0].season.tolist(),
            "missing_markets": [m for m, col in [("1X2", "odds_1x2_prematch_pct"), ("OU2.5", "ou_odds_pct"), ("AH", "ah_odds_pct")]
                                if (g[col] == 0).all()],
            "never_available": ["lineups", "players", "injuries", "possession", "formations"],
        }
    return out


def historical_data_report(db: Database, cov: pd.DataFrame | None = None) -> dict:
    cov = coverage_matrix(db) if cov is None else cov
    q = db.scalar
    rep = {
        "generated_at": iso(utcnow()),
        "total_matches": q("SELECT COUNT(*) FROM match"),
        "total_finished": q("SELECT COUNT(*) FROM match WHERE status='FINISHED'"),
        "total_seasons": int(len(cov)) if not cov.empty else 0,
        "total_competitions": q("SELECT COUNT(DISTINCT competition_id) FROM match"),
        "total_teams": q("SELECT COUNT(DISTINCT team_id) FROM (SELECT home_team_id team_id FROM match UNION SELECT away_team_id FROM match)"),
        "total_players": 0,
        "total_bookmakers": q("SELECT COUNT(*) FROM bookmaker WHERE is_aggregate=0"),
        "total_odds_snapshots": q("SELECT COUNT(*) FROM odds_snapshot"),
        "total_events_matches": q("SELECT COUNT(*) FROM match WHERE stats_json LIKE '%by_team%'"),
        "total_lineups": 0,
        "total_xg_records": q("SELECT COUNT(*) FROM match WHERE stats_json LIKE '%by_team%'"),
        "oldest_data": q("SELECT MIN(match_date) FROM match"),
        "newest_result": q("SELECT MAX(match_date) FROM match WHERE status='FINISHED'"),
        "newest_fixture": q("SELECT MAX(match_date) FROM match"),
        "conflicts": q("SELECT COUNT(*) FROM data_conflict"),
        "disputed_scores": q("SELECT COUNT(*) FROM match WHERE score_disputed=1"),
        "entity_review_open": q("SELECT COUNT(*) FROM entity_review WHERE status='OPEN'"),
        "raw_datasets": q("SELECT COUNT(*) FROM source_record"),
        "ingestion_errors": q("SELECT COUNT(*) FROM ingestion_issue WHERE severity='ERROR'"),
        "ingestion_warnings": q("SELECT COUNT(*) FROM ingestion_issue WHERE severity='WARN'"),
    }
    if not cov.empty:
        by_comp = cov.groupby("competition").agg(seasons=("season", "count"), results=("results", "sum"),
                                                 odds=("odds_1x2_prematch_pct", "mean"), exact=("exact_kickoff_pct", "mean"))
        by_comp["coverage_index"] = by_comp.seasons * (1 + by_comp.odds + by_comp.exact)
        rep["best_covered_competition"] = str(by_comp.coverage_index.idxmax())
        rep["worst_covered_competition"] = str(by_comp.coverage_index.idxmin())
        rep["point_in_time_coverage"] = {
            "seasons_results_pit_exact": int(cov.pit_capability.str.contains("RESULTS_PIT_EXACT").sum()),
            "seasons_results_pit_daily_only": int(cov.pit_capability.str.contains("RESULTS_PIT_DAILY").sum()),
            "seasons_with_pit_odds": int(cov.pit_capability.str.contains("ODDS_PIT").sum()),
        }
        rep["missing_timestamps_seasons"] = cov[cov.exact_kickoff_pct < 0.5].season.tolist()
    rep["gaps"] = gaps_report(db, cov)
    return rep


def persist_quality(db: Database, cov: pd.DataFrame) -> list[dict]:
    now = iso(utcnow())
    out = []
    for r in cov.to_dict("records"):
        dup, wrong = structural_anomalies(db, r["competition"], int(r["season"][:4]))
        q = season_quality(r, dup, wrong)
        scope_id = f"{r['competition']}:{r['season']}"
        db.execute("INSERT INTO data_quality(scope, scope_id, score, weakest, components, computed_at) VALUES (?,?,?,?,?,?)",
                   ("competition_season", scope_id, q["score"], q["weakest"], dumps(q), now))
        out.append({"scope_id": scope_id, **q})
    return out
