# Environment audit (STEP 1)

Build environment, 2026-09-29 (a cloud Linux container - **not** the target Windows PC).
Re-run on your machine with `python -m sports_engine audit-env` (or `scripts\setup.ps1`).

| Item | Build environment | Target |
|---|---|---|
| OS | Linux 6.18 (x86_64) | Windows 11 + PowerShell |
| Python | 3.11.15 (uv-managed venv) | 3.11+ |
| CPU | 4 vCPU Intel Xeon 2.1 GHz | any modern CPU |
| GPU | none | optional, unused (CPU-first; no CUDA code path) |
| RAM | 15 GB | 8 GB is enough for Serie A; 16 GB for many leagues |
| Disk | 30 GB free | raw lake for top-5 leagues is well under 1 GB |
| Git | new, empty repository on branch `claude/affectionate-einstein-o4q6ob` | - |
| Network | HTTPS via proxy; GitHub raw reachable; football-data reachable but robots.txt blocks AI agents (not used); Club Elo API 502 | your connection |
| Pre-installed packages | only requests, PyYAML, Jinja2 | installed by `setup.ps1` |
| Existing code/config | none | - |

Installed in the venv: numpy 2.4, pandas 3.0, scipy 1.17, scikit-learn 1.9, FastAPI 0.142,
uvicorn, DuckDB 1.5, pyarrow, pytest 9.1, hypothesis 6.168, httpx.
