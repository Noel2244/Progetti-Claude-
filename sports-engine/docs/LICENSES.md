# Licenses, terms and legal data policy

Researched on **2026-09-29**. Terms change: re-read them before relying on this page.
"Free" never means "unrestricted". Raw third-party data is **never committed** to this
repository (`data/` is git-ignored) and is never redistributed.

## Policy (enforced in code where possible)

| Rule | Enforcement |
|---|---|
| Honest, identifying User-Agent; never impersonate a browser/bot | `PoliteDownloader` rejects `Mozilla*` agents |
| robots.txt honoured, never bypassed | `PoliteDownloader.robots_allowed`; a disallow aborts the provider |
| No bypass of authentication, paywalls, anti-bot systems, rate limits | no such code exists; per-host rate limiting + backoff + `Retry-After` |
| Opt-in for sources with restrictive terms | `football_data` requires `enabled` **and** `terms_acknowledged` |
| Only allow-listed hosts (SSRF guard) | host allow-list per provider, also checked after redirects |
| No redistribution of raw data | `data/` in `.gitignore`; reports contain only derived aggregates |
| Attribution where required | provider `attribution` field; shown in reports/docs |

## Sources used

| Source | License / terms | Commercial | Redistribution | Automated access | Attribution | Decision |
|---|---|---|---|---|---|---|
| **engsoccerdata** (J. Curley) | GPL (>=2) R package; README: free for non-commercial use, cite | No (per README) | GPL terms; we do not redistribute | GitHub raw files, polite | "James P. Curley (2016). engsoccerdata" | **USED** (long-term results) |
| **openfootball / football.json** | **CC0-1.0** public domain | Yes | Yes | GitHub raw files | not required | **USED** (results, kickoff times, current fixtures) |
| **StatsBomb Open Data** | StatsBomb public data user agreement (LICENSE.pdf) | see agreement | see agreement | GitHub raw files | **Required**: credit StatsBomb + logo when publishing | **USED** (match metadata; events opt-in) |
| **Football-Data.co.uk** | "FREE, however its use is intended for private individuals only, NOT commercial or data training products using automated bots/scrapers/AI"; "for the purposes of league match prediction only" | **No** | **No** | robots.txt allows generic agents but **blocks AI crawlers** (GPTBot, ChatGPT-User, Anthropic-AI, Claude-Web, ClaudeBot, ...) | "Data: Football-Data.co.uk" | **OPT-IN, user-run only** - see below |
| Local manual import | user's responsibility | - | - | - | - | **USED** (`data/inbox`) |

### Football-Data.co.uk - how this engine handles it

* The site's `robots.txt` explicitly blocks AI agents. Therefore **the AI assistant that
  built this project did not bulk-download it**; the only accesses were reading the
  terms/notes pages and one CSV header to design the parser. No football-data file is
  stored in this repository.
* The downloader for it is **disabled by default**. The owner of this installation - a
  private individual using it for personal league-match prediction - may enable it by
  setting both `providers.football_data.enabled: true` and
  `providers.football_data.terms_acknowledged: true` in `config.yaml` after reading
  <https://www.football-data.co.uk/data.php> and the disclaimer. It then downloads
  slowly (3 s between requests), with an honest user agent, honouring robots.txt,
  and never re-downloads closed seasons.
* Alternatively download the CSVs manually in a browser and drop them into
  `data/inbox/football_data/` (`import-inbox`), which is the most conservative option.
* If your use is or becomes commercial, or feeds a data-training product, **do not use
  this source**.

## Sources evaluated and rejected (for automated use)

| Source | Reason |
|---|---|
| FBref / Sports-Reference | Terms restrict scraping and impose strict rate limits; underlying data licensed from a commercial provider. Rejected for automated acquisition. |
| Transfermarkt | Terms prohibit automated scraping. Rejected. |
| Understat | No official API or explicit terms for automated use; scraping undocumented JSON embedded in pages. Rejected by default (not verified in this session). |
| WhoScored / Sofascore / FotMob | Anti-bot protections and restrictive terms; bypassing is forbidden by this project's policy. Rejected. |
| Repackaged football-data mirrors on GitHub/Kaggle | Redistributions of Football-Data content inherit its "private use, no redistribution" terms; using them to route around the original site's robots.txt would violate the spirit of the terms. Rejected. |
| Club Elo API | Useful, free, but no explicit terms found and the endpoint was unreachable (HTTP 502) from this environment. Not integrated; our own Elo is computed from raw results instead. |
| Paid odds APIs (The Odds API, API-Football, Sportmonks, ...) | Paid services must never be mandatory. Adapters may be added later as **optional**, keys in `.env`, off by default. |

## Libraries (runtime)

numpy (BSD-3), pandas (BSD-3), scipy (BSD-3), scikit-learn (BSD-3), PyYAML (MIT),
requests (Apache-2.0); optional: FastAPI (MIT), uvicorn (BSD-3), DuckDB (MIT),
pyarrow (Apache-2.0), pytest (MIT), hypothesis (MPL-2.0), httpx (BSD-3).
No GPL code is vendored into this repository.
