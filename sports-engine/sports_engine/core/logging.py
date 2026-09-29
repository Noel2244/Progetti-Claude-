"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

_SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)
_CONFIGURED = False


def _secret_values() -> list[str]:
    return [v for k, v in os.environ.items() if _SECRET_ENV.search(k) and v and len(v) >= 6]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        secrets = _secret_values()
        if secrets:
            msg = record.getMessage()
            for s in secrets:
                msg = msg.replace(s, "***REDACTED***")
            record.msg, record.args = msg, ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", json_format: bool = True, logfile: str | None = None) -> None:
    global _CONFIGURED
    root = logging.getLogger("sports_engine")
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if logfile:
        os.makedirs(os.path.dirname(logfile) or ".", exist_ok=True)
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(JsonFormatter() if json_format else logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        h.addFilter(RedactingFilter())
        root.addHandler(h)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not name.startswith("sports_engine"):
        name = f"sports_engine.{name}"
    return logging.getLogger(name)


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, msg, extra={"fields": fields})
