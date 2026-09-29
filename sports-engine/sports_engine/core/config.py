"""Configuration loading (config.yaml + optional .env), with safe path resolution."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ENV_HOME = "SPORTS_ENGINE_HOME"
ENV_CONFIG = "SPORTS_ENGINE_CONFIG"
ENV_DATA_DIR = "SPORTS_ENGINE_DATA_DIR"


def find_project_root(start: Path | None = None) -> Path:
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for p in [here, *here.parents]:
        if (p / "config.yaml").exists() and (p / "sports_engine").is_dir():
            return p
    # fall back to the package's parent directory
    return Path(__file__).resolve().parents[2]


def load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env reader (KEY=VALUE lines). Values are never logged."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


@dataclass
class Settings:
    root: Path
    raw: dict[str, Any]
    secrets: dict[str, str] = field(default_factory=dict, repr=False)

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def path(self, dotted: str, default: str | None = None) -> Path:
        value = self.get(dotted, default)
        if value is None:
            raise KeyError(dotted)
        p = Path(value)
        return p if p.is_absolute() else (self.root / p)

    @property
    def data_dir(self) -> Path:
        env = os.environ.get(ENV_DATA_DIR)
        return Path(env).resolve() if env else self.path("paths.data_dir", "data")

    @property
    def database_path(self) -> Path:
        env = os.environ.get(ENV_DATA_DIR)
        if env:
            return Path(env).resolve() / "sports_engine.sqlite"
        return self.path("paths.database", "data/sports_engine.sqlite")

    @property
    def reports_dir(self) -> Path:
        return self.path("paths.reports_dir", "reports")

    def secret(self, name: str) -> str | None:
        return os.environ.get(name) or self.secrets.get(name)

    def with_overrides(self, overrides: dict[str, Any]) -> "Settings":
        return Settings(root=self.root, raw=_deep_merge(self.raw, overrides), secrets=self.secrets)


def load_settings(config_path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    root = find_project_root()
    cfg_path = Path(config_path or os.environ.get(ENV_CONFIG) or root / "config.yaml")
    raw: dict[str, Any] = {}
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if overrides:
        raw = _deep_merge(raw, overrides)
    if raw.get("mode", "paper") != "paper":
        raise ValueError("Only 'paper' mode exists. Real-money execution is not supported by design.")
    secrets = load_dotenv(root / ".env")
    return Settings(root=root, raw=raw, secrets=secrets)
