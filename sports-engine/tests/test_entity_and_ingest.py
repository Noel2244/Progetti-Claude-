"""Entity resolution + full ingestion (lake -> DB -> canonical) on invented fixtures."""

from __future__ import annotations

import json
from datetime import date

import pytest

from sports_engine.data.lake import RawDataLake
from sports_engine.entity.resolution import (
    FixtureObs,
    TeamEntry,
    TeamRegistry,
    TeamResolver,
    normalize_team_name,
)
from sports_engine.pipeline.acquisition import descriptor_meta
from sports_engine.pipeline.ingest import Ingestor
from sports_engine.providers.base import DatasetDescriptor

from .conftest import FIXTURES


def test_normalization():
    assert normalize_team_name("US Salernitana 1919") == "salernitana"
    assert normalize_team_name("A.C.R. Messina") == "messina"
    assert normalize_team_name("1. FC Köln") == "koln"


def test_registry_alias_collision_fails():
    with pytest.raises(ValueError):
        TeamRegistry([TeamEntry("ita-a", "A", "ITA", ("Verona",)), TeamEntry("ita-b", "B", "ITA", ("verona",))])


def test_ambiguous_names_are_never_merged():
    reg = TeamRegistry([TeamEntry("ita-hellas", "Hellas Verona", "ITA", ("Hellas Verona",)),
                        TeamEntry("ita-chievo", "Chievo Verona", "ITA", ("Chievo Verona",))])
    r = TeamResolver(reg)
    res = r.resolve_static("ITA", "Verona")
    assert res.team_id is None and res.method == "AMBIGUOUS" and set(res.candidates) == {"ita-hellas", "ita-chievo"}
    assert r.resolve_static("ITA", "Hellas Verona FC").team_id == "ita-hellas"      # normalized unique
    assert r.resolve_static("ITA", "Some New Club").method == "NEW_ENTITY"


def test_cooccurrence_resolution():
    reg = TeamRegistry([TeamEntry("ita-x", "Xcity", "ITA", ("Xcity",))])
    r = TeamResolver(reg, min_evidence=3, min_share=0.9)
    # in the reference source, "ita-inter" played ita-x on these dates (home or away)
    ref = {}
    fixtures = []
    for i in range(5):
        d = date(2020, 1, 1 + 7 * i)
        home_is_x = i % 2 == 0
        if home_is_x:
            ref.setdefault((d, "ita-x"), []).append(("ita-inter", "H"))
            fixtures.append(FixtureObs(d, "Xcity", "FC Internazionale Milano", 2019))
        else:
            ref.setdefault((d, "ita-x"), []).append(("ita-inter", "A"))
            fixtures.append(FixtureObs(d, "FC Internazionale Milano", "Xcity", 2019))
    res = r.cooccurrence("FC Internazionale Milano", fixtures, {"Xcity": "ita-x"}, ref)
    assert res.team_id == "ita-inter" and res.method == "COOCCURRENCE"


def _store(lake, provider, key, fname, kind, comp="ITA1", season=None, ext=None):
    d = DatasetDescriptor(provider, key, None, kind, comp, season, file_ext=ext or fname.rsplit(".", 1)[1])
    lake.store_file(provider, key, FIXTURES / fname, d.file_ext, extra=descriptor_meta(d))


def test_full_ingest_merges_sources_and_records_conflicts(settings, db):
    lake = RawDataLake(settings.data_dir)
    _store(lake, "engsoccerdata", "italy", "engsoccerdata_italy.csv", "results")
    _store(lake, "openfootball", "2008-09/it.1", "openfootball_it1.json", "results", season="2008-2009")
    _store(lake, "football_data", "mmz4281/0809/I1", "football_data_old.csv", "results_odds", season="2008-2009")
    rep = Ingestor(settings, db, lake).run_all()
    # the only contract error is the implausible far-future fixture (2099) - rejected, not stored
    assert rep.errors == 1
    assert db.scalar("SELECT code FROM ingestion_issue WHERE severity='ERROR'") == "DATE_RANGE"
    # 'Alphaville' / 'Alphaville FC' etc. must collapse into one team each
    teams = {r["team_id"] for r in db.query("SELECT DISTINCT home_team_id AS team_id FROM match UNION SELECT away_team_id FROM match")}
    assert len(teams) == 3
    matches = db.query("SELECT * FROM match ORDER BY match_date")
    first = matches[0]
    assert json.loads(first["sources"]) == ["football_data", "openfootball", "engsoccerdata"]
    # engsoccerdata/football_data say 3-0, openfootball says 3-1 -> recorded conflict, priority winner kept
    conflicts = db.query("SELECT * FROM data_conflict WHERE field='score'")
    assert conflicts and first["score_disputed"] == 1
    assert (first["home_goals"], first["away_goals"]) == (3, 0)
    # the openfootball-only stale fixture + far-future fixture exist but are not FINISHED
    statuses = {m["status"] for m in matches}
    assert "FINISHED" in statuses
    # odds landed on canonical matches with timestamps
    n_odds = db.scalar("SELECT COUNT(*) FROM odds_snapshot")
    assert n_odds > 0
    assert db.scalar("SELECT COUNT(*) FROM odds_snapshot WHERE available_at IS NULL") == 0
    # re-running is idempotent and keeps ids stable
    ids_before = {m["match_id"] for m in matches}
    Ingestor(settings, db, lake).run_all(force=True)
    assert {m["match_id"] for m in db.query("SELECT match_id FROM match")} == ids_before
    assert all(r["method"] in ("REGISTRY", "NORMALIZED", "NEW_ENTITY", "COOCCURRENCE", "KNOWN")
               for r in db.query("SELECT method FROM team_alias"))
