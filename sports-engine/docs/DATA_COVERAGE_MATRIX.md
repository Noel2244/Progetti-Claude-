# Data coverage matrix

Generated from the build-session database on 2026-09-29 (`python -m sports_engine coverage`; full CSV: `reports/coverage/coverage_matrix.csv`). Percentages are shares of the season's matches.

## Summary (Serie A, ITA1)

- Matches: 29,584 (29,254 finished) | seasons: 96 | teams: 70
- Oldest data: 1929-10-06 | newest result: 2026-09-20 | newest fixture: 2027-05-30
- Missing seasons: 1943-1944 (not played (WWII)), 1944-1945 (not played (WWII))
- Structurally anomalous seasons (non double round-robin): 1945-1946, 1946-1947, 1947-1948, 1952-1953, 1965-1966
- Seasons with pre-match odds: 0 | with closing odds: 0 | with xG: 0
- Missing markets everywhere: 1X2, OU2.5, AH
- Never available from integrated sources: lineups, players, injuries, possession, formations
- Point-in-time: 13 seasons with exact kickoff times, 83 date-only (daily granularity), 0 with point-in-time odds
- Conflicts recorded: 217 | disputed scores: 1 | open entity reviews: 0

## Per season

Columns not shown are 0% everywhere in this build (odds, closing odds, bookmakers, lineups, players, injuries, possession, formations, xG events). `DQ` = data-quality score, `weakest` = weakest component.

| season | state | teams | matches | results | exact KO | multi-source | managers | disputed | sources | PIT | DQ | weakest |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| 2026-2027 | IN_PROGRESS | 20 | 380 | 13% | 32% | 0% | 0% | 0 | openfootball | RESULTS_PIT_DAILY+NO_ODDS | 0.80 | corroboration |
| 2025-2026 | COMPLETE | 20 | 380 | 100% | 100% | 0% | 0% | 0 | openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.84 | corroboration |
| 2024-2025 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2023-2024 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2022-2023 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2021-2022 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2020-2021 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 1 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2019-2020 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2018-2019 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2017-2018 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2016-2017 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2015-2016 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 100% | 0 | engsoccerdata,openfootball,statsbomb | RESULTS_PIT_EXACT+NO_ODDS | 0.98 | source_reliability |
| 2014-2015 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2013-2014 | COMPLETE | 20 | 380 | 100% | 100% | 100% | 0% | 0 | engsoccerdata,openfootball | RESULTS_PIT_EXACT+NO_ODDS | 0.95 | source_reliability |
| 2012-2013 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2011-2012 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2010-2011 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2009-2010 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2008-2009 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2007-2008 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2006-2007 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2005-2006 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2004-2005 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2003-2004 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2002-2003 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2001-2002 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 2000-2001 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1999-2000 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1998-1999 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1997-1998 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1996-1997 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1995-1996 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1994-1995 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1993-1994 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1992-1993 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1991-1992 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1990-1991 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1989-1990 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1988-1989 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1987-1988 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1986-1987 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata,statsbomb | RESULTS_PIT_DAILY+NO_ODDS | 0.81 | corroboration |
| 1985-1986 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1984-1985 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1983-1984 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1982-1983 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1981-1982 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1980-1981 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1979-1980 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1978-1979 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1977-1978 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1976-1977 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1975-1976 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1974-1975 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1973-1974 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1972-1973 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1971-1972 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1970-1971 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1969-1970 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1968-1969 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1967-1968 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1966-1967 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1965-1966 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1964-1965 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1963-1964 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1962-1963 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1961-1962 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1960-1961 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1959-1960 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1958-1959 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1957-1958 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1956-1957 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1955-1956 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1954-1955 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1953-1954 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1952-1953 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1951-1952 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1950-1951 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1949-1950 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1948-1949 | COMPLETE | 20 | 380 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1947-1948 | COMPLETE | 23 | 390 | 77% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.70 | corroboration |
| 1946-1947 | COMPLETE | 20 | 370 | 97% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.76 | corroboration |
| 1945-1946 | COMPLETE | 25 | 348 | 58% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.64 | corroboration |
| 1942-1943 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1941-1942 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1940-1941 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1939-1940 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1938-1939 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1937-1938 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1936-1937 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1935-1936 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1934-1935 | COMPLETE | 16 | 240 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1933-1934 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1932-1933 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1931-1932 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1930-1931 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |
| 1929-1930 | COMPLETE | 18 | 306 | 100% | 0% | 0% | 0% | 0 | engsoccerdata | RESULTS_PIT_DAILY+NO_ODDS | 0.78 | corroboration |

## Reading the quality score

The score is a weighted mean of completeness, consistency, timestamp quality, source reliability, corroboration (>= 2 sources), cross-source agreement and freshness (see `quality/scoring.py`). It is always shown with its weakest component; a single number never hides a poor component. Pre-2013 seasons score lower mainly because they rest on a single secondary source with date-only timestamps.
