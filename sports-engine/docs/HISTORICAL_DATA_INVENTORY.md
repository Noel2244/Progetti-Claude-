# Historical data inventory

Inventory as acquired in the build session (2026-09-29) for the vertical slice (Serie A,
`ITA1`). Regenerate with `python -m sports_engine coverage`.

## Acquired and ingested

| Provider | Datasets | Rows (Serie A) | Seasons | Fields | Class | Timestamp quality |
|---|---|---|---|---|---|---|
| engsoccerdata | `italy` (1 file, 28,825 rows) | 28,824 matches | 1929/30 - 2024/25 | date, teams, FT score | LONG_TERM, POINT_IN_TIME_READY (daily) | DATE_ONLY |
| openfootball | 14 files `20XX-YY/it.1` | 5,320 matches (incl. 330 future fixtures) | 2013/14 - 2026/27 | date, local kickoff, FT + HT score, round | MEDIUM_TERM, RECENT, LIVE | EXACT (local time) |
| statsbomb | `competitions` + 2 season files | 381 matches | 1986/87 (1), 2015/16 (380) | kickoff, score, managers, venue, referee, match week | POST_MATCH_ONLY, NON_POINT_IN_TIME | APPROXIMATE |

Canonical result: **29,584 Serie A matches**, 1929-10-06 -> 2027-05-30 (330 scheduled),
96 seasons present, 144 (source, raw name) pairs -> 70 canonical teams (0 ambiguous,
0 left in the review queue). 5,060 matches have an exact kickoff, 24,524 are date-only.

Not acquired in the session: football-data.co.uk (opt-in, user-run - see LICENSES.md).
When the owner enables it, the same pipeline adds 1993/94- results with shots, corners,
cards, fouls, referees and bookmaker odds (1X2 from 2000/01, O/U 2.5 and Asian handicap,
closing odds from 2019/20).

## Findings from ingestion (why the conflict engine exists)

1. **StatsBomb kickoff timezone is inconsistent.** Against openfootball (whose times match
   the standard Serie A slots 12:30/15:00/18:00/20:45), 206 of 380 Serie A 2015/16 StatsBomb
   kickoffs differ by exactly one hour, concentrated in winter months (CET): +1 h in
   Nov-Mar, 0 in Apr-Oct, and a handful at -2 h (look like UTC). StatsBomb kickoffs are
   therefore stamped APPROXIMATE and demoted in `source_priority.kickoff`; the 216
   disagreements are still recorded in `data_conflict`.
2. **Awarded result.** Hellas Verona - Roma (2020-09-19) was drawn 0-0 on the pitch and
   awarded 3-0 to Verona (ineligible player). engsoccerdata has 0-0, openfootball 3-0.
   Recorded as a score conflict; the match is `score_disputed=1` and excluded from model
   training and evaluation.
3. **Format drift.** openfootball 2025-26 contains 36 matches whose `score` is a bare
   `[home, away]` list instead of `{"ft": [...]}`. The parser accepts both and emits
   `FORMAT_DRIFT` warnings.
4. **Missing upstream files.** openfootball has no Serie A files for 2010-11 .. 2012-13
   (HTTP 404) - recorded as coverage gaps, not failures.
5. **Missing result.** openfootball 2024-25 lacks the score of Venezia - Juventus
   (2025-05-25); engsoccerdata provides it, so the canonical match is complete.
6. **Non-standard historical formats.** 1945/46 - 1947/48 (post-war split groups / 23-team
   league) fail the double round-robin structure checks and are flagged as anomalous seasons.

## Classification summary

* LONG_TERM: engsoccerdata (1929-2025), football-data (1993-, opt-in).
* MEDIUM_TERM / RECENT: openfootball (2013-).
* POINT_IN_TIME_READY: results from all sources (a result is public at full time);
  daily granularity for DATE_ONLY seasons, exact for 2013/14+.
* NON_POINT_IN_TIME: StatsBomb open data as a *dataset* (published years later).
* POST_MATCH_ONLY: StatsBomb events/xG for the match itself.
* LIVE_OUT_OF_SAMPLE: openfootball current-season fixtures; paper predictions; user odds.

## Not available from any integrated legal source (explicitly visible gaps)

Historical odds (until football-data is enabled by the owner), lineups, starting XI,
substitutions, player availability, injuries, suspensions, player statistics, formations,
tactical data, possession, xG beyond two StatsBomb seasons, manager changes beyond
StatsBomb metadata. The coverage matrix shows these as 0%, and the decision engine treats
lineups as unknown.
