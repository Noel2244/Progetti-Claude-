# Market engine

## Margin removal (`market/margin.py`)

For decimal odds o_i, raw implied pi_i = 1/o_i, margin = sum(pi) - 1.

| Method | Formula | Notes |
|---|---|---|
| multiplicative | p = pi / sum(pi) | directive minimum; ignores favourite-longshot bias |
| additive | p = pi - margin/n | can go negative for long shots -> rejected then |
| power (default) | p = pi^k, sum p = 1 | good bias correction, simple |
| shin | insider-trading model, solve z | classic for UK markets |
| odds_ratio | p = pi / (c + pi - c*pi) | Cheung (2015) |

Stored: raw probabilities, fair probabilities, method, margin, method parameter.
Property tests (Hypothesis) verify validity, normalisation and ordering for every method.

## Consensus (`market/consensus.py`)

1. Only individual books (aggregate Max/Avg columns are dropped when books exist).
2. Latest *visible* price per book/selection at decision time; incomplete books skipped.
3. Each book's margin removed; **consensus = per-selection median**, renormalised;
   trimmed mean and a sharp-book reference (pinnacle / betfair exchange, when present in
   the data) are reported alongside; **dispersion** = std across books (market uncertainty).
4. Best available price per selection (and the book offering it).

## Stale / suspicious prices

* `STALE_ODDS` - newest visible snapshot older than `max_odds_staleness_hours` (hard NO BET).
* `OUTLIER_BEST_PRICE` - the best price's book is > 6 pp away from consensus with >= 3 books:
  a single stale quote is not treated as value (hard NO BET).
* `SINGLE_BOOK` - no consensus possible (soft: at most WATCH).
* Missing snapshots -> `NO_ODDS` -> INSUFFICIENT_DATA.

## Odds history and movement

`odds_movement()` returns opening, current, min, max, median, number of snapshots,
relative movement and movement per hour for any selection, from visible snapshots only.

## Closing line value (`market/clv.py`)

`clv_price = odds_taken / closing_odds - 1` and `clv_fair = odds_taken * p_close_fair - 1`
(EV of the taken price at the margin-free closing consensus). Paper outcomes and backtests
store both; the API aggregates them per market/competition.
