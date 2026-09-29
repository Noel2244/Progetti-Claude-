"""Ingestion: raw lake -> validated source records -> entities -> canonical matches.

Stages (each idempotent):

1. ``ingest_raw``      parse the latest revision of every dataset, enforce data
                       contracts, replace the derived rows of that dataset;
2. ``resolve_entities`` conservative team resolution (see entity/resolution.py);
3. ``build_canonical``  merge sources into one match per fixture, record every
                       disagreement in ``data_conflict``, compute point-in-time
                       availability, and materialise ``odds_snapshot``.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sports_engine import SCHEMA_VERSION
from sports_engine.core.config import Settings
from sports_engine.core.enums import MatchStatus, TimestampQuality
from sports_engine.core.hashing import short_id, stable_hash
from sports_engine.core.logging import get_logger, log_event
from sports_engine.core.timeutils import iso, next_local_midnight_utc, parse_iso, utcnow
from sports_engine.data.lake import RawDataLake
from sports_engine.database.db import Database, dumps
from sports_engine.entity.competitions import get_competition, load_competitions
from sports_engine.entity.resolution import FixtureObs, TeamRegistry, TeamResolver
from sports_engine.normalization.contracts import enforce_contract
from sports_engine.pipeline.acquisition import descriptor_from_entry
from sports_engine.providers.football_data import AGGREGATE_BOOKMAKERS
from sports_engine.providers.registry import PROVIDER_CLASSES, get_provider

log = get_logger("ingest")

RESOLUTION_ORDER = ["engsoccerdata", "football_data", "openfootball", "statsbomb", "local_csv"]


@dataclass
class IngestReport:
    datasets_ingested: list[str] = field(default_factory=list)
    datasets_skipped: int = 0
    matches_staged: int = 0
    odds_staged: int = 0
    errors: int = 0
    warnings: int = 0
    resolutions: dict[str, int] = field(default_factory=dict)
    review_queue: int = 0
    canonical_matches: int = 0
    conflicts: int = 0
    odds_snapshots: int = 0


class Ingestor:
    def __init__(self, settings: Settings, db: Database, lake: RawDataLake | None = None):
        self.settings = settings
        self.db = db
        self.lake = lake or RawDataLake(settings.data_dir)

    # ================================================================ stage 1
    def ingest_raw(self, force: bool = False, report: IngestReport | None = None) -> IngestReport:
        report = report or IngestReport()
        now = iso(utcnow())
        for provider_name in PROVIDER_CLASSES:
            provider = get_provider(provider_name, self.settings)
            for key, entry in sorted(self.lake.latest_by_key(provider_name).items()):
                desc = descriptor_from_entry(entry)
                if desc.kind == "metadata":
                    continue
                parser_version = getattr(sys.modules[type(provider).__module__], "PARSER_VERSION", "1")
                done = self.db.scalar("SELECT parser_version FROM source_record WHERE raw_sha256=?", (entry.sha256,))
                if done == parser_version and not force:
                    report.datasets_skipped += 1
                    continue
                try:
                    content = self.lake.read(entry)
                    parsed = provider.parse(desc, content, entry.sha256, acquired_at=parse_iso(entry.downloaded_at))
                    parsed = enforce_contract(parsed)
                except Exception as exc:  # one bad file must not stop the pipeline or corrupt the DB
                    self.db.execute(
                        "INSERT INTO ingestion_issue(raw_sha256, provider, severity, code, message, record_key, created_at) VALUES (?,?,?,?,?,?,?)",
                        (entry.sha256, provider_name, "ERROR", "PARSER_CRASH", f"{type(exc).__name__}: {exc}"[:500], key, now),
                    )
                    report.errors += 1
                    log_event(log, "parser crash", provider=provider_name, dataset=key, error=str(exc))
                    continue
                n_err = sum(1 for i in parsed.issues if i.severity == "ERROR")
                n_warn = len(parsed.issues) - n_err
                with self.db.transaction() as c:
                    c.execute("DELETE FROM source_match WHERE source=? AND dataset_key=?", (provider_name, key))
                    c.execute("DELETE FROM source_odds WHERE source=? AND dataset_key=?", (provider_name, key))
                    c.execute("DELETE FROM source_match_stats WHERE source=? AND dataset_key=?", (provider_name, key))
                    c.executemany(
                        """INSERT OR REPLACE INTO source_match(source, source_match_key, dataset_key, competition_id, season,
                           season_start_year, match_date, kickoff_utc, kickoff_local, timestamp_quality, home_team_raw,
                           away_team_raw, home_goals, away_goals, ht_home_goals, ht_away_goals, status, round, venue,
                           referee, stats_json, extra_json, raw_sha256, raw_row, ingested_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [(m.source, m.source_match_key, key, m.competition_id, m.season, m.season_start_year,
                          m.match_date.isoformat(), iso(m.kickoff_utc), m.kickoff_local_time, m.timestamp_quality.value,
                          m.home_team_raw, m.away_team_raw, m.home_goals, m.away_goals, m.ht_home_goals, m.ht_away_goals,
                          m.status.value, m.round, m.venue, m.referee, dumps(m.stats) if m.stats else None,
                          dumps(m.extra) if m.extra else None, m.raw_sha256, m.raw_row, now) for m in parsed.matches],
                    )
                    c.executemany(
                        """INSERT OR IGNORE INTO source_odds(source, dataset_key, source_match_key, bookmaker, market, selection,
                           line, odds, snapshot_type, available_at, timestamp_quality, raw_sha256)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [(o.source, key, o.source_match_key, o.bookmaker, o.market, o.selection, o.line, o.odds,
                          o.snapshot_type.value, iso(o.available_at), o.timestamp_quality.value, o.raw_sha256)
                         for o in parsed.odds if o.available_at is not None],
                    )
                    c.executemany(
                        "INSERT OR REPLACE INTO source_match_stats(source, dataset_key, source_match_key, stats_json, raw_sha256) VALUES (?,?,?,?,?)",
                        [(provider_name, key, k, dumps(v), entry.sha256) for k, v in parsed.stat_updates.items()],
                    )
                    c.executemany(
                        "INSERT INTO ingestion_issue(raw_sha256, provider, severity, code, message, record_key, created_at) VALUES (?,?,?,?,?,?,?)",
                        [(entry.sha256, provider_name, i.severity, i.code, i.message[:500], i.key, now) for i in parsed.issues[:5000]],
                    )
                    c.execute(
                        """INSERT OR REPLACE INTO source_record(raw_sha256, provider, dataset_key, url, downloaded_at, license_id,
                           terms_ref, acquisition, parser_version, ingested_at, n_matches, n_odds, n_errors, n_warnings)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (entry.sha256, provider_name, key, entry.url, entry.downloaded_at, entry.license_id, entry.terms_ref,
                         entry.acquisition, parser_version, now, len(parsed.matches), len(parsed.odds), n_err, n_warn),
                    )
                report.datasets_ingested.append(f"{provider_name}:{key}")
                report.matches_staged += len(parsed.matches)
                report.odds_staged += len(parsed.odds)
                report.errors += n_err
                report.warnings += n_warn
        return report

    # ================================================================ stage 2
    def resolve_entities(self, report: IngestReport | None = None) -> IngestReport:
        report = report or IngestReport()
        registry = TeamRegistry.load()
        comps = load_competitions()
        now = iso(utcnow())
        # teams from registry
        self.db.executemany(
            "INSERT OR IGNORE INTO team(team_id, name, country, auto_created, source, created_at, updated_at, schema_version) VALUES (?,?,?,?,?,?,?,?)",
            [(e.team_id, e.name, e.country, 0, "registry", now, now, SCHEMA_VERSION) for e in registry.entries.values()],
        )
        stored = {(r["source"], r["country"], r["alias"]): r["team_id"] for r in self.db.query("SELECT * FROM team_alias")}
        known = {(c, a.lower()): t for (s, c, a), t in stored.items() if not t.startswith("__")}
        names = {r["team_id"]: r["name"] for r in self.db.query("SELECT team_id, name FROM team")}
        resolver = TeamResolver(registry, known, names)
        counts: dict[str, int] = defaultdict(int)

        present = [r["source"] for r in self.db.query("SELECT DISTINCT source FROM source_match")]
        order = [s for s in RESOLUTION_ORDER if s in present] + [s for s in present if s not in RESOLUTION_ORDER]
        for source in order:
            rows = self.db.query(
                "SELECT competition_id, season_start_year, match_date, home_team_raw, away_team_raw FROM source_match WHERE source=?",
                (source,),
            )
            by_country: dict[str, set[str]] = defaultdict(set)
            fixtures: dict[str, list[FixtureObs]] = defaultdict(list)
            for r in rows:
                country = comps[r["competition_id"]].country
                by_country[country].update([r["home_team_raw"], r["away_team_raw"]])
                fixtures[country].append(FixtureObs(date.fromisoformat(r["match_date"]), r["home_team_raw"],
                                                    r["away_team_raw"], r["season_start_year"]))
            for country, raw_names in by_country.items():
                resolved: dict[str, str] = {}
                pending: dict[str, object] = {}
                for raw in sorted(raw_names):
                    if (source, country, raw) in stored:
                        tid = stored[(source, country, raw)]
                        if not tid.startswith("__"):
                            resolved[raw] = tid
                            counts["EXISTING"] += 1
                            continue
                    res = resolver.resolve_static(country, raw)
                    if res.team_id:
                        resolved[raw] = res.team_id
                        self._store_alias(source, country, raw, res, now)
                        counts[res.method] += 1
                    else:
                        pending[raw] = res
                if pending:
                    reference = self._reference_fixtures(exclude_source=source, country=country)
                    for _ in range(3):  # iterate: newly resolved names provide evidence for others
                        progressed = False
                        for raw in sorted(pending):
                            co = resolver.cooccurrence(raw, fixtures[country], resolved, reference) if reference else None
                            if co and co.team_id and co.team_id not in resolved.values():
                                resolved[raw] = co.team_id
                                self._store_alias(source, country, raw, co, now)
                                counts["COOCCURRENCE"] += 1
                                del pending[raw]
                                progressed = True
                            elif co is not None and co.method == "AMBIGUOUS":
                                pending[raw] = co
                        if not progressed:
                            break
                    for raw, res in sorted(pending.items()):
                        if res.method == "NEW_ENTITY":
                            tid = resolver.new_entity_id(country, raw)
                            resolver.register(country, raw, tid, raw)
                            self.db.execute(
                                "INSERT OR IGNORE INTO team(team_id, name, country, auto_created, source, created_at, updated_at, schema_version) VALUES (?,?,?,?,?,?,?,?)",
                                (tid, raw, country, 1, source, now, now, SCHEMA_VERSION),
                            )
                            res.team_id, res.confidence = tid, 0.9
                            resolved[raw] = tid
                            self._store_alias(source, country, raw, res, now)
                            counts["NEW_ENTITY"] += 1
                        else:
                            counts["AMBIGUOUS"] += 1
                            self.db.execute(
                                "INSERT OR IGNORE INTO entity_review(entity_type, source, country, raw_name, candidates, reason, created_at) VALUES (?,?,?,?,?,?,?)",
                                ("team", source, country, raw, dumps(res.candidates), res.evidence or "ambiguous", now),
                            )
                self._check_injective(source, country, resolved, now)
                for raw, tid in resolved.items():
                    resolver.register(country, raw, tid)
                # apply to source rows (reset first so revoked mappings do not linger)
                self.db.executemany(
                    "UPDATE source_match SET home_team_id=NULL WHERE source=? AND home_team_raw=?",
                    [(source, raw) for raw in raw_names],
                )
                self.db.executemany(
                    "UPDATE source_match SET away_team_id=NULL WHERE source=? AND away_team_raw=?",
                    [(source, raw) for raw in raw_names],
                )
                self.db.executemany(
                    "UPDATE source_match SET home_team_id=? WHERE source=? AND home_team_raw=?",
                    [(tid, source, raw) for raw, tid in resolved.items()],
                )
                self.db.executemany(
                    "UPDATE source_match SET away_team_id=? WHERE source=? AND away_team_raw=?",
                    [(tid, source, raw) for raw, tid in resolved.items()],
                )
        report.resolutions = dict(counts)
        report.review_queue = self.db.scalar("SELECT COUNT(*) FROM entity_review WHERE status='OPEN'") or 0
        return report

    def _store_alias(self, source, country, raw, res, now) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO team_alias(source, country, alias, team_id, method, confidence, evidence, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (source, country, raw, res.team_id, res.method, res.confidence, res.evidence, now),
        )

    def _reference_fixtures(self, exclude_source: str, country: str) -> dict:
        comps = [cid for cid, c in load_competitions().items() if c.country == country]
        if not comps:
            return {}
        q = ",".join("?" * len(comps))
        rows = self.db.query(
            f"""SELECT match_date, home_team_id, away_team_id FROM source_match
                WHERE source != ? AND home_team_id IS NOT NULL AND away_team_id IS NOT NULL AND competition_id IN ({q})""",
            (exclude_source, *comps),
        )
        ref: dict = defaultdict(list)
        for r in rows:
            d = date.fromisoformat(r["match_date"])
            ref[(d, r["home_team_id"])].append((r["away_team_id"], "H"))
            ref[(d, r["away_team_id"])].append((r["home_team_id"], "A"))
        return ref

    def _check_injective(self, source: str, country: str, resolved: dict[str, str], now: str) -> None:
        """Two raw names of one source in the same season must not collapse into one team."""
        comps = [cid for cid, c in load_competitions().items() if c.country == country]
        if not comps:
            return
        q = ",".join("?" * len(comps))
        rows = self.db.query(
            f"""SELECT season, home_team_raw AS n FROM source_match WHERE source=? AND competition_id IN ({q})
                UNION SELECT season, away_team_raw FROM source_match WHERE source=? AND competition_id IN ({q})""",
            (source, *comps, source, *comps),
        )
        per_season: dict[tuple[str, str], set[str]] = defaultdict(set)
        for r in rows:
            tid = resolved.get(r["n"])
            if tid:
                per_season[(r["season"], tid)].add(r["n"])
        for (season, tid), raws in per_season.items():
            if len(raws) > 1:
                for raw in raws:
                    resolved.pop(raw, None)
                    self.db.execute("DELETE FROM team_alias WHERE source=? AND country=? AND alias=?", (source, country, raw))
                    self.db.execute(
                        "INSERT OR IGNORE INTO entity_review(entity_type, source, country, raw_name, candidates, reason, created_at) VALUES (?,?,?,?,?,?,?)",
                        ("team", source, country, raw, dumps([tid]), f"non-injective mapping in season {season}: {sorted(raws)}", now),
                    )

    # ================================================================ stage 3
    def build_canonical(self, report: IngestReport | None = None) -> IngestReport:
        report = report or IngestReport()
        prio_results = self.settings.get("source_priority.results", RESOLUTION_ORDER)
        prio_kickoff = self.settings.get("source_priority.kickoff", RESOLUTION_ORDER)
        rank_r = {s: i for i, s in enumerate(prio_results)}
        rank_k = {s: i for i, s in enumerate(prio_kickoff)}
        comps = load_competitions()
        now = iso(utcnow())
        today = date.today()
        rows = self.db.query(
            """SELECT * FROM source_match WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL
               ORDER BY competition_id, season_start_year, home_team_id, away_team_id, match_date"""
        )
        extra_stats = defaultdict(dict)
        for r in self.db.query("SELECT source, source_match_key, stats_json FROM source_match_stats"):
            extra_stats[(r["source"], r["source_match_key"])].update(json.loads(r["stats_json"]))
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            groups[(r["competition_id"], r["season_start_year"], r["home_team_id"], r["away_team_id"])].append(r)

        match_rows, conflicts, links = [], [], []
        for (cid, sy, home, away), recs in groups.items():
            comp = comps[cid]
            clusters: list[list[dict]] = []
            for rec in sorted(recs, key=lambda x: x["match_date"]):
                d = date.fromisoformat(rec["match_date"])
                best, best_gap = None, None
                for cl in clusters:
                    if any(x["source"] == rec["source"] for x in cl):
                        continue
                    gap = min(abs((d - date.fromisoformat(x["match_date"])).days) for x in cl)
                    if best_gap is None or gap < best_gap:
                        best, best_gap = cl, gap
                if best is not None and (best_gap <= 3 or (not comp.is_cup and len(clusters) == 1)):
                    best.append(rec)
                else:
                    clusters.append([rec])
            for n, cl in enumerate(clusters):
                mid = short_id("m", cid, sy, home, away) if n == 0 else short_id("m", cid, sy, home, away, n)
                merged, cl_conflicts = self._merge_cluster(mid, cl, comp, rank_r, rank_k, today, extra_stats)
                match_rows.append(merged)
                conflicts.extend(cl_conflicts)
                links.extend((mid, x["source"], x["source_match_key"]) for x in cl)

        with self.db.transaction() as c:
            c.execute("UPDATE source_match SET match_id=NULL")
            c.executemany("UPDATE source_match SET match_id=? WHERE source=? AND source_match_key=?", links)
            c.execute("DELETE FROM match")
            c.executemany(
                """INSERT INTO match(match_id, competition_id, season, season_start_year, match_date, kickoff_utc,
                   kickoff_time_known, timestamp_quality, home_team_id, away_team_id, home_goals, away_goals,
                   ht_home_goals, ht_away_goals, status, result_available_at, primary_source, sources, n_sources,
                   has_conflict, score_disputed, stats_json, data_version, schema_version, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [tuple(m[k] for k in MATCH_COLUMNS) + (SCHEMA_VERSION, now, now) for m in match_rows],
            )
            c.execute("DELETE FROM data_conflict WHERE entity_type='match'")
            c.executemany(
                """INSERT OR REPLACE INTO data_conflict(entity_type, entity_id, field, source_a, value_a, source_b, value_b,
                   resolution, resolution_reason, detected_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [(*x, now) for x in conflicts],
            )
            c.execute("DELETE FROM odds_snapshot")
            c.execute(
                """INSERT OR IGNORE INTO odds_snapshot(match_id, source, bookmaker, market, selection, line, odds,
                   snapshot_type, available_at, timestamp_quality, raw_sha256, ingested_at)
                   SELECT sm.match_id, so.source, so.bookmaker, so.market, so.selection, so.line, so.odds,
                          so.snapshot_type, so.available_at, so.timestamp_quality, so.raw_sha256, ?
                   FROM source_odds so JOIN source_match sm
                     ON sm.source = so.source AND sm.source_match_key = so.source_match_key
                   WHERE sm.match_id IS NOT NULL""",
                (now,),
            )
            c.executemany(
                "INSERT OR IGNORE INTO bookmaker(bookmaker_id, is_aggregate, created_at) VALUES (?,?,?)",
                [(b["bookmaker"], int(b["bookmaker"] in AGGREGATE_BOOKMAKERS), now)
                 for b in self.db.query("SELECT DISTINCT bookmaker FROM source_odds")],
            )
            c.executemany(
                "INSERT OR REPLACE INTO competition(competition_id, name, country, tier, type, timezone, created_at, updated_at, schema_version) VALUES (?,?,?,?,?,?,?,?,?)",
                [(k, v.name, v.country, v.tier, v.type, v.timezone, now, now, SCHEMA_VERSION) for k, v in comps.items()],
            )
        report.canonical_matches = len(match_rows)
        report.conflicts = len(conflicts)
        report.odds_snapshots = self.db.scalar("SELECT COUNT(*) FROM odds_snapshot") or 0
        log_event(log, "canonical built", matches=len(match_rows), conflicts=len(conflicts))
        return report

    def _merge_cluster(self, mid, cl, comp, rank_r, rank_k, today, extra_stats):
        conflicts = []
        big = 99
        with_score = [x for x in cl if x["home_goals"] is not None]
        primary = min(with_score or cl, key=lambda x: rank_r.get(x["source"], big))
        exact = [x for x in cl if x["timestamp_quality"] == TimestampQuality.EXACT.value and x["kickoff_utc"]]
        ko_rec = min(exact, key=lambda x: rank_k.get(x["source"], big)) if exact else None
        kickoff = parse_iso(ko_rec["kickoff_utc"]) if ko_rec else None
        if kickoff is not None:
            match_date = kickoff.astimezone(ZoneInfo(comp.timezone)).date()
        else:
            match_date = date.fromisoformat(primary["match_date"])
        # ---- conflicts (never silently overwritten)
        for x in with_score:
            if x is primary:
                continue
            if (x["home_goals"], x["away_goals"]) != (primary["home_goals"], primary["away_goals"]):
                conflicts.append(("match", mid, "score", primary["source"], f"{primary['home_goals']}-{primary['away_goals']}",
                                  x["source"], f"{x['home_goals']}-{x['away_goals']}", primary["source"],
                                  "source_priority.results"))
            for f in ("ht_home_goals", "ht_away_goals"):
                if x[f] is not None and primary[f] is not None and x[f] != primary[f]:
                    conflicts.append(("match", mid, f, primary["source"], str(primary[f]), x["source"], str(x[f]),
                                      primary["source"], "source_priority.results"))
        for x in cl:
            d = date.fromisoformat(x["match_date"])
            if x is not primary and abs((d - date.fromisoformat(primary["match_date"])).days) > 1:
                conflicts.append(("match", mid, "match_date", primary["source"], primary["match_date"], x["source"],
                                  x["match_date"], ko_rec["source"] if ko_rec else primary["source"],
                                  "exact kickoff source wins; otherwise results priority"))
        for x in cl:
            if ko_rec is not None and x is not ko_rec and x["kickoff_utc"]:
                dt = abs((parse_iso(x["kickoff_utc"]) - kickoff).total_seconds())
                if dt > 20 * 60:
                    conflicts.append(("match", mid, "kickoff_utc", ko_rec["source"], ko_rec["kickoff_utc"], x["source"],
                                      x["kickoff_utc"], ko_rec["source"],
                                      f"EXACT beats {x['timestamp_quality']}; then source_priority.kickoff"))
        # ---- status & availability
        if primary["home_goals"] is not None:
            status = MatchStatus.FINISHED.value
        elif any(x["status"] == MatchStatus.SCHEDULED.value for x in cl) and match_date >= today - timedelta(days=1):
            status = MatchStatus.SCHEDULED.value
        elif any(x["status"] == MatchStatus.POSTPONED.value for x in cl):
            status = MatchStatus.POSTPONED.value
        else:
            status = MatchStatus.UNKNOWN.value
        result_available_at = None
        if status == MatchStatus.FINISHED.value:
            if kickoff is not None:
                hours = float(self.settings.get(
                    "point_in_time.result_buffer_hours_cup" if comp.is_cup else "point_in_time.result_buffer_hours_league",
                    4.0 if comp.is_cup else 3.0))
                result_available_at = iso(kickoff + timedelta(hours=hours))
            else:
                result_available_at = iso(next_local_midnight_utc(match_date, comp.timezone))
        stats: dict = {}
        for x in sorted(cl, key=lambda x: -rank_r.get(x["source"], big)):
            if x["stats_json"]:
                stats.update(json.loads(x["stats_json"]))
            stats.update(extra_stats.get((x["source"], x["source_match_key"]), {}))
        sources = sorted({x["source"] for x in cl}, key=lambda s: rank_r.get(s, big))
        tq = TimestampQuality.EXACT.value if kickoff else TimestampQuality.DATE_ONLY.value
        return {
            "match_id": mid,
            "competition_id": primary["competition_id"],
            "season": primary["season"],
            "season_start_year": primary["season_start_year"],
            "match_date": match_date.isoformat(),
            "kickoff_utc": iso(kickoff),
            "kickoff_time_known": int(kickoff is not None),
            "timestamp_quality": tq,
            "home_team_id": primary["home_team_id"],
            "away_team_id": primary["away_team_id"],
            "home_goals": primary["home_goals"],
            "away_goals": primary["away_goals"],
            "ht_home_goals": primary["ht_home_goals"],
            "ht_away_goals": primary["ht_away_goals"],
            "status": status,
            "result_available_at": result_available_at,
            "primary_source": primary["source"],
            "sources": json.dumps(sources),
            "n_sources": len(sources),
            "has_conflict": int(bool(conflicts)),
            "score_disputed": int(any(c[2] == "score" for c in conflicts)),
            "stats_json": dumps(stats) if stats else None,
            "data_version": stable_hash(sorted(x["raw_sha256"] or "" for x in cl), 16),
        }, conflicts

    def run_all(self, force: bool = False) -> IngestReport:
        rep = self.ingest_raw(force=force)
        self.resolve_entities(rep)
        self.build_canonical(rep)
        return rep


MATCH_COLUMNS = [
    "match_id", "competition_id", "season", "season_start_year", "match_date", "kickoff_utc", "kickoff_time_known",
    "timestamp_quality", "home_team_id", "away_team_id", "home_goals", "away_goals", "ht_home_goals", "ht_away_goals",
    "status", "result_available_at", "primary_source", "sources", "n_sources", "has_conflict", "score_disputed", "stats_json",
    "data_version",
]
