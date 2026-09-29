# Repository research

Checked on 2026-09-29 by reading the repositories' GitHub pages. README claims were not
taken at face value: the decision column records what we actually do with each one.
"n/v" = not verifiable from the page at research time.

| Repository | Purpose | License | Maintenance | Python | Strengths | Weaknesses / concerns | Integration difficulty | Decision | Reason |
|---|---|---|---|---|---|---|---|---|---|
| [ML-KULeuven/socceraction](https://github.com/ML-KULeuven/socceraction) | SPADL event format, VAEP, xT | MIT | Maintainers state it is **not actively developed** (reproducibility of research); 816 stars | 3.9-3.12 | Clean event abstraction; StatsBomb/Opta/Wyscout loaders | Unmaintained; heavy deps; event data only | Medium | **Reference only** | Useful later for event features (xT/VAEP) once event data is integrated; not needed for the vertical slice |
| [statsbomb/open-data](https://github.com/statsbomb/open-data) | Free event data, lineups, 360 | StatsBomb user agreement (attribution required) | Active (commits 2025-2026) | - | High-quality events + xG | Sparse coverage; published years after matches | Low | **Integrated** (`providers/statsbomb.py`) | Match metadata + optional event/xG aggregation |
| [statsbomb/statsbombpy](https://github.com/statsbomb/statsbombpy) | API client | StatsBomb user agreement | Active | - | Official client | Extra dependency; we only need raw JSON | Low | **Not used** | Direct raw JSON is simpler and keeps provenance/hashes |
| [openfootball/football.json](https://github.com/openfootball/football.json) | Results/fixtures JSON | CC0-1.0 | Active (daily auto-update of current season) | - | Public domain; fixtures incl. future | Community data, occasional gaps / format drift (seen: list-shaped scores 2025-26) | Low | **Integrated** | Only CC0 source with current fixtures |
| [jalapic/engsoccerdata](https://github.com/jalapic/engsoccerdata) | Historical results 1871- | GPL>=2 (README: non-commercial, cite) | Updated Feb 2026 (results through 2024/25) | R package (we read CSVs) | Very long history | European leagues updated less often; dates only | Low | **Integrated** | Long-term priors / Elo history |
| [martineastwood/penaltyblog](https://github.com/martineastwood/penaltyblog) | Poisson / Dixon-Coles / bivariate Poisson, ratings, overround removal, scrapers | MIT | Active; 228 stars | 3.x | Broad, fast (Cython) | Scrapers (Understat etc.) whose terms are the user's responsibility; compiled extension on Windows | Medium | **Reference / cross-check only** | We implement the models ourselves so the point-in-time interface, uncertainty and gradients are under our control; penaltyblog is a good independent cross-check of DC fits |
| [probberechts/soccerdata](https://github.com/probberechts/soccerdata) | Scrapers: FBref, Understat, WhoScored, Sofascore, ClubElo, ESPN, Football-Data, SoFIFA | Apache-2.0 | Active; 2.1k stars; README warns it breaks when sites change | 3.x | Wide coverage | **Web scraping** of sites whose terms restrict it; fragile | Low (technically) | **Rejected** for automated acquisition | Conflicts with the legal data policy (see LICENSES.md) |
| [mberk/shin](https://github.com/mberk/shin) | Shin implied probabilities | MIT | Active; 105 stars | >=3.9 (Rust core) | Fast, well-tested | Extra compiled dependency | Low | **Not used** (own implementation) | Our `market/margin.py` implements Shin, power, odds-ratio, additive, multiplicative with property tests |
| [EFS-OpenSource/calibration-framework](https://github.com/EFS-OpenSource/calibration-framework) (netcal) | Calibration methods + metrics | Apache-2.0 | Active (v1.4); 380 stars | 3.x | Many methods (BBQ, ENIR, beta) | Oriented to NN confidence; heavy deps | Medium | **Optional future** | Our calibrators cover identity/temperature/Dirichlet/isotonic/Platt; netcal could be added in the Research Lab |
| [classifier-calibration/PyCalib](https://github.com/classifier-calibration/PyCalib) | Classifier calibration (incl. Dirichlet) | BSD-3 | Active, small (20 stars) | 3.x | Reference Dirichlet calibration | Small community | Low | **Reference** | Our Dirichlet calibrator follows Kull et al. 2019 |
| [mlflow/mlflow](https://github.com/mlflow/mlflow) | Experiment tracking | Apache-2.0 | Very active; 28k stars; file-based local store | 3.x | Standard tooling | Large dependency tree; not needed for one user | Low | **Deferred** | SQLite experiment registry with immutability + multiple-testing accounting is sufficient now; MLflow can be added as an optional exporter |
| scikit-learn | Isotonic regression, metrics | BSD-3 | Very active | 3.x | Reliable | - | Low | **Used** | Isotonic calibration |
| scipy | Optimisation, distributions | BSD-3 | Very active | 3.x | L-BFGS-B, Brent | - | Low | **Used** | Model fitting |

## Implementations studied but re-implemented

* **Dixon-Coles (1997)** - low-score correction and exponential time weighting
  (xi ~ 0.0065 per half-week = 0.0019/day). Implemented with an analytic gradient,
  verified against finite differences (`tests/test_models.py`).
* **Maher (1982) Poisson** - static and time-weighted variants.
* **Elo** - World Football Elo goal-difference multiplier; ordered-logit link.
* **Shin (1992/1993), power, odds-ratio (Cheung 2015)** margin removal.
* **Dirichlet calibration (Kull et al., 2019)**, temperature scaling (Guo et al., 2017).

## Security notes

No third-party code is executed dynamically; nothing downloaded is ever imported
or run; calibrators are persisted as JSON (never pickle).
