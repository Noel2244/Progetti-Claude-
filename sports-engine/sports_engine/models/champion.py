"""Champion / Challenger registry and promotion quality gates.

A challenger may replace the champion only if ALL gates pass:

1. no_leakage        - the temporal/feature leakage test-suite passed for this code version
2. adequate_sample   - enough out-of-sample predictions
3. out_of_sample     - walk-forward evaluation (always true for engine backtests)
4. calibration       - mean ECE and calibration slopes within tolerance
5. beats_reference   - significantly better log loss than the reference (CI excludes 0)
6. robustness        - better than the reference in a majority of seasons
7. market_benchmark  - evaluated against the market when odds exist; a model that is
                       significantly worse than the market cannot drive betting decisions
8. reproducibility   - code version (clean tree), dataset fingerprint and config recorded

Promotion is never based on ROI.
"""

from __future__ import annotations

import json

from sports_engine.core.timeutils import iso, utcnow
from sports_engine.database.db import Database, dumps

GATE_DEFAULTS = {"min_n": 1000, "max_ece": 0.03, "slope_low": 0.8, "slope_high": 1.25, "min_season_win_share": 0.6}


def evaluate_gates(result, model: str, reference: str, meta: dict, leakage_tests_passed: bool | None,
                   thresholds: dict | None = None) -> dict:
    th = {**GATE_DEFAULTS, **(thresholds or {})}
    m = result.metrics.get(f"{model}:calibrated") or result.metrics.get(f"{model}:raw")
    gates: dict[str, dict] = {}
    gates["no_leakage"] = {"pass": leakage_tests_passed is True,
                           "detail": "leakage suite passed" if leakage_tests_passed else "leakage suite not verified for this run"}
    gates["adequate_sample"] = {"pass": bool(m and m["n"] >= th["min_n"]), "detail": f"n={m['n'] if m else 0} (min {th['min_n']})"}
    gates["out_of_sample"] = {"pass": True, "detail": "walk-forward, point-in-time snapshots"}
    if m:
        slopes = {c: v["slope"] for c, v in m["classes"].items()}
        ok = m["ece_mean"] <= th["max_ece"] and all(th["slope_low"] <= s <= th["slope_high"] for s in slopes.values())
        gates["calibration"] = {"pass": ok, "detail": f"ECE={m['ece_mean']:.4f}, slopes={ {k: round(v, 2) for k, v in slopes.items()} }"}
    else:
        gates["calibration"] = {"pass": False, "detail": "no metrics"}
    comp = result.comparisons.get(f"{model}_vs_{reference}")
    gates["beats_reference"] = {"pass": bool(comp and comp["ci_high"] < 0),
                                "detail": f"{reference}: diff {comp['mean_diff']:+.4f} CI [{comp['ci_low']:+.4f}, {comp['ci_high']:+.4f}]" if comp else "no comparison"}
    ps = result.per_season
    if not ps.empty and reference in set(ps["model"]) and model in set(ps["model"]):
        pv = ps.pivot_table(index="season", columns="model", values="log_loss").dropna(subset=[model, reference])
        share = float((pv[model] < pv[reference]).mean()) if len(pv) else 0.0
        gates["robustness"] = {"pass": share >= th["min_season_win_share"], "detail": f"better in {share:.0%} of {len(pv)} seasons"}
    else:
        gates["robustness"] = {"pass": False, "detail": "per-season comparison unavailable"}
    mk = result.comparisons.get(f"{model}_vs_market")
    if mk is None:
        gates["market_benchmark"] = {"pass": False, "detail": "UNAVAILABLE - no odds in the evaluation window; the model may serve probabilities but not betting decisions"}
    else:
        gates["market_benchmark"] = {"pass": mk["ci_low"] <= 0, "detail": f"vs market diff {mk['mean_diff']:+.4f} CI [{mk['ci_low']:+.4f}, {mk['ci_high']:+.4f}]"}
    cv = str(meta.get("code_version", "unknown"))
    gates["reproducibility"] = {"pass": cv != "unknown" and not cv.endswith("-dirty") and bool(meta.get("dataset_fingerprint")),
                                "detail": f"code={cv}, dataset={meta.get('dataset_fingerprint')}"}
    probability_gates = ["no_leakage", "adequate_sample", "out_of_sample", "calibration", "beats_reference", "robustness", "reproducibility"]
    return {
        "model": model, "reference": reference, "gates": gates,
        "probability_champion_eligible": all(gates[g]["pass"] for g in probability_gates),
        "betting_eligible": all(g["pass"] for g in gates.values()),
    }


class ModelRegistry:
    def __init__(self, db: Database):
        self.db = db

    def register(self, name: str, version: str, config: dict, gates: dict | None = None, role: str = "CHALLENGER") -> str:
        key = f"{name}@{version}"
        now = iso(utcnow())
        self.db.execute(
            """INSERT INTO model_registry(model_key, name, version, role, config, gates, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(model_key) DO UPDATE SET gates=excluded.gates, updated_at=excluded.updated_at""",
            (key, name, version, role, dumps(config), dumps(gates or {}), now, now))
        self._event(key, "REGISTERED", None, gates)
        return key

    def champion(self) -> dict | None:
        rows = self.db.query("SELECT * FROM model_registry WHERE role='CHAMPION'")
        return rows[0] if rows else None

    def promote(self, key: str, gate_report: dict, scope: str = "probability") -> None:
        eligible = gate_report["probability_champion_eligible"] if scope == "probability" else gate_report["betting_eligible"]
        if not eligible:
            failed = [g for g, v in gate_report["gates"].items() if not v["pass"]]
            raise PermissionError(f"promotion refused for {key}: failed gates {failed}")
        now = iso(utcnow())
        cur = self.champion()
        if cur and cur["model_key"] != key:
            self.db.execute("UPDATE model_registry SET role='CHALLENGER', updated_at=? WHERE model_key=?", (now, cur["model_key"]))
            self._event(cur["model_key"], "DEMOTED", f"replaced by {key}", None)
        self.db.execute("UPDATE model_registry SET role='CHAMPION', gates=?, updated_at=? WHERE model_key=?",
                        (dumps(gate_report), now, key))
        self._event(key, "PROMOTED", scope, gate_report)

    def retire(self, key: str, reason: str) -> None:
        self.db.execute("UPDATE model_registry SET role='RETIRED', updated_at=? WHERE model_key=?", (iso(utcnow()), key))
        self._event(key, "RETIRED", reason, None)

    def _event(self, key: str, event: str, reason: str | None, details) -> None:
        self.db.execute("INSERT INTO model_event(model_key, event, reason, details, created_at) VALUES (?,?,?,?,?)",
                        (key, event, reason, dumps(details) if details is not None else None, iso(utcnow())))

    def list(self) -> list[dict]:
        rows = self.db.query("SELECT model_key, name, version, role, gates, updated_at FROM model_registry ORDER BY role, model_key")
        for r in rows:
            g = json.loads(r["gates"] or "{}")
            r["gates_passed"] = {k: v["pass"] for k, v in g.get("gates", {}).items()} if isinstance(g, dict) else {}
            r.pop("gates")
        return rows
