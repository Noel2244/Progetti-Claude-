"""Task orchestration with retry, timeout budget, checkpoints and partial failure.

A failed task is recorded and - unless marked ``critical`` - the pipeline
continues with whatever is still safe to run. Every attempt is logged to the
``pipeline_run`` table so a run can be inspected and resumed.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from sports_engine.core.hashing import short_id
from sports_engine.core.logging import get_logger, log_event
from sports_engine.core.timeutils import iso, utcnow
from sports_engine.database.db import Database, dumps

log = get_logger("pipeline")


@dataclass
class TaskResult:
    name: str
    status: str            # OK | FAILED | SKIPPED | DEGRADED
    attempts: int
    output: Any = None
    error: str | None = None
    seconds: float = 0.0


@dataclass
class PipelineRunner:
    db: Database
    run_id: str = field(default_factory=lambda: short_id("run", iso(utcnow()), time.time_ns()))
    results: list[TaskResult] = field(default_factory=list)

    def done_before(self, name: str) -> bool:
        return bool(self.db.scalar("SELECT 1 FROM pipeline_run WHERE run_id=? AND task=? AND status='OK'", (self.run_id, name)))

    def run(self, name: str, fn: Callable[[], Any], retries: int = 1, critical: bool = False,
            requires: list[str] | None = None, backoff: float = 2.0) -> TaskResult:
        if self.done_before(name):                      # checkpoint -> resume
            r = TaskResult(name, "SKIPPED", 0, "already completed in this run")
            self.results.append(r)
            return r
        failed_deps = [d for d in (requires or []) if not any(x.name == d and x.status in ("OK", "DEGRADED") for x in self.results)]
        if failed_deps:
            r = TaskResult(name, "SKIPPED", 0, error=f"dependencies failed: {failed_deps}")
            self._log(r, iso(utcnow()))
            self.results.append(r)
            return r
        started = iso(utcnow())
        t0 = time.time()
        attempt = 0
        while True:
            attempt += 1
            try:
                out = fn()
                status = "DEGRADED" if isinstance(out, dict) and out.get("degraded") else "OK"
                r = TaskResult(name, status, attempt, out, seconds=round(time.time() - t0, 2))
                break
            except Exception as exc:  # noqa: BLE001 - one task must not bring down the pipeline
                err = f"{type(exc).__name__}: {exc}"
                log_event(log, "task failed", task=name, attempt=attempt, error=err)
                if attempt > retries:
                    r = TaskResult(name, "FAILED", attempt, error=err + "\n" + traceback.format_exc(limit=3),
                                   seconds=round(time.time() - t0, 2))
                    break
                time.sleep(backoff ** attempt)
        self._log(r, started)
        self.results.append(r)
        if r.status == "FAILED" and critical:
            raise RuntimeError(f"critical task {name} failed: {r.error}")
        return r

    def _log(self, r: TaskResult, started: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO pipeline_run(run_id, task, status, started_at, finished_at, attempts, details) VALUES (?,?,?,?,?,?,?)",
            (self.run_id, r.name, r.status, started, iso(utcnow()), r.attempts,
             dumps({"error": r.error, "output": r.output if isinstance(r.output, (dict, list, str, int, float, type(None))) else str(r.output)})[:20000]))

    def summary(self) -> dict:
        return {"run_id": self.run_id, "tasks": [{"task": r.name, "status": r.status, "attempts": r.attempts,
                                                  "seconds": r.seconds, "error": (r.error or "").split("\n")[0] or None}
                                                 for r in self.results],
                "ok": all(r.status in ("OK", "SKIPPED", "DEGRADED") for r in self.results)}
