---
description: Run the daily pipeline and summarise the paper predictions (NO BET is a valid result)
---
Run `python -m sports_engine daily` from the project root, then read the newest file in
reports/daily/. Summarise: data health (overdue results, provider status), number of upcoming
fixtures, status counts, and every CANDIDATE/STRONG_CANDIDATE with its probability interval,
EV and reasons. If there are none, say so plainly. Never invent odds, injuries or lineups.
