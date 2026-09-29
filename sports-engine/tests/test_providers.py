"""Provider parsers on small, invented fixture files (no third-party data is redistributed)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from sports_engine.core.enums import MatchStatus, SnapshotType, TimestampQuality
from sports_engine.normalization.contracts import enforce_contract
from sports_engine.providers.base import DatasetDescriptor
from sports_engine.providers.engsoccerdata import EngSoccerDataProvider
from sports_engine.providers.football_data import (
    FootballDataProvider,
    fd_season_code,
    prematch_collection_estimate,
)
from sports_engine.providers.openfootball import OpenFootballProvider
from sports_engine.providers.statsbomb import StatsBombProvider

from .conftest import FIXTURES


def test_football_data_modern_parse():
    p = FootballDataProvider()
    d = DatasetDescriptor("football_data", "mmz4281/2425/I1", None, "results_odds", "ITA1", "2024-2025")
    ds = p.parse(d, (FIXTURES / "football_data_modern.csv").read_bytes(), "sha")
    assert len(ds.matches) == 2                       # D1 row filtered, empty row skipped
    m = ds.matches[0]
    assert (m.home_team_raw, m.home_goals, m.away_goals, m.ht_home_goals) == ("Alphaville", 2, 1, 1)
    assert m.kickoff_utc == datetime(2024, 9, 21, 16, 0, tzinfo=timezone.utc)   # 17:00 UK (BST) -> 16:00 UTC
    assert m.timestamp_quality == TimestampQuality.EXACT
    assert m.stats["home_shots"] == 14 and m.stats["away_red"] == 0
    odds = [o for o in ds.odds if o.source_match_key == m.source_match_key]
    books = {o.bookmaker for o in odds}
    assert {"bet365", "pinnacle", "vcbet", "agg_max", "agg_avg"} <= books
    vc = [o for o in odds if o.bookmaker == "vcbet" and o.selection == "H" and o.market == "1X2"]
    assert len(vc) == 1 and vc[0].odds == 1.80 and vc[0].snapshot_type == SnapshotType.PRE_MATCH
    closing = [o for o in odds if o.snapshot_type == SnapshotType.CLOSING]
    assert closing and all(o.available_at == m.kickoff_utc for o in closing)
    pre = [o for o in odds if o.snapshot_type == SnapshotType.PRE_MATCH]
    assert all(o.available_at < m.kickoff_utc for o in pre)
    assert all(o.timestamp_quality == TimestampQuality.APPROXIMATE for o in pre)
    ou = [o for o in odds if o.market == "OU"]
    assert {(o.bookmaker, o.selection) for o in ou} >= {("bet365", "OVER"), ("pinnacle", "UNDER")}
    ah = [o for o in odds if o.market == "AH"]
    assert {o.line for o in ah if o.snapshot_type == SnapshotType.PRE_MATCH} == {-0.75}


def test_football_data_old_format_date_only():
    p = FootballDataProvider()
    d = DatasetDescriptor("football_data", "mmz4281/0809/I1", None, "results_odds", "ITA1", "2008-2009")
    ds = p.parse(d, (FIXTURES / "football_data_old.csv").read_bytes(), "sha")
    assert len(ds.matches) == 2
    m = ds.matches[0]
    assert m.match_date == date(2008, 9, 13) and m.kickoff_utc is None
    assert m.timestamp_quality == TimestampQuality.DATE_ONLY
    assert not [o for o in ds.odds if o.snapshot_type == SnapshotType.CLOSING]
    assert {"agg_betbrain_max", "agg_betbrain_avg", "bet365", "williamhill"} <= {o.bookmaker for o in ds.odds}


def test_collection_estimate_schedule():
    # Saturday match -> Friday 18:00 UK; Wednesday match -> Tuesday 18:00 UK
    sat = prematch_collection_estimate(date(2024, 9, 21), None)
    assert sat.date() == date(2024, 9, 20)
    wed = prematch_collection_estimate(date(2024, 9, 25), None)
    assert wed.date() == date(2024, 9, 24)
    # capped before an early kickoff
    ko = datetime(2024, 9, 24, 16, 0, tzinfo=timezone.utc)
    assert prematch_collection_estimate(date(2024, 9, 24), ko) <= ko


def test_football_data_is_opt_in():
    from sports_engine.core.config import load_settings
    s = load_settings()
    p = FootballDataProvider(s)
    assert not p.is_enabled() and "opt-in" in p.enabled_reason()
    s2 = s.with_overrides({"providers": {"football_data": {"enabled": True}}})
    assert "terms" in FootballDataProvider(s2).enabled_reason()
    s3 = s.with_overrides({"providers": {"football_data": {"enabled": True, "terms_acknowledged": True}}})
    assert FootballDataProvider(s3).is_enabled()


def test_season_code():
    assert fd_season_code(1993) == "9394" and fd_season_code(1999) == "9900" and fd_season_code(2024) == "2425"


def test_engsoccerdata_parse_filters_tier():
    p = EngSoccerDataProvider()
    d = DatasetDescriptor("engsoccerdata", "italy", None, "results", "ITA1")
    ds = p.parse(d, (FIXTURES / "engsoccerdata_italy.csv").read_bytes(), "sha")
    assert len(ds.matches) == 3
    assert all(m.status == MatchStatus.FINISHED and m.timestamp_quality == TimestampQuality.DATE_ONLY for m in ds.matches)
    assert ds.matches[0].season == "2008-2009"


def test_openfootball_parse_handles_drift_and_states():
    p = OpenFootballProvider()
    d = DatasetDescriptor("openfootball", "2008-09/it.1", None, "results", "ITA1", "2008-2009")
    ds = p.parse(d, (FIXTURES / "openfootball_it1.json").read_bytes(), "sha")
    by = {(m.home_team_raw, m.match_date): m for m in ds.matches}
    assert by[("Betatown Calcio", date(2008, 9, 17))].home_goals == 1                # list-shaped score
    assert any(i.code == "FORMAT_DRIFT" for i in ds.issues)
    assert by[("Gammacity FC", date(2008, 9, 21))].status == MatchStatus.UNKNOWN     # past, no score
    fut = by[("Alphaville", date(2099, 1, 1))]
    assert fut.status == MatchStatus.SCHEDULED and fut.timestamp_quality == TimestampQuality.DATE_ONLY
    first = by[("Alphaville", date(2008, 9, 13))]
    assert first.kickoff_utc == datetime(2008, 9, 13, 18, 45, tzinfo=timezone.utc)    # 20:45 CEST


def test_statsbomb_parse_marks_kickoff_approximate():
    p = StatsBombProvider()
    d = DatasetDescriptor("statsbomb", "matches/12/1", None, "results", "ITA1", "2008-2009")
    ds = p.parse(d, (FIXTURES / "statsbomb_matches.json").read_bytes(), "sha")
    m = ds.matches[0]
    assert m.timestamp_quality == TimestampQuality.APPROXIMATE
    assert m.extra["home_managers"] == ["Coach A"] and m.venue == "Alpha Arena"


def test_contract_rejects_bad_records():
    p = OpenFootballProvider()
    d = DatasetDescriptor("openfootball", "2008-09/it.1", None, "results", "ITA1", "2008-2009")
    ds = p.parse(d, (FIXTURES / "openfootball_it1.json").read_bytes(), "sha")
    ds.matches[0].home_goals = -1
    ds.matches[1].away_team_raw = ds.matches[1].home_team_raw
    clean = enforce_contract(ds)
    codes = {i.code for i in clean.issues}
    assert {"GOALS_RANGE", "SAME_TEAM", "DATE_RANGE"} <= codes     # 2099 fixture is implausible too
    assert len(clean.matches) == len(ds.matches) - 3
