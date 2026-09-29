"""Competition registry access."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REGISTRY_DIR = Path(__file__).parent / "registry"


@dataclass(frozen=True)
class Competition:
    competition_id: str
    name: str
    country: str
    tier: int
    type: str
    timezone: str
    season_style: str
    sources: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def source_code(self, provider: str) -> Any:
        return self.sources.get(provider)

    @property
    def is_cup(self) -> bool:
        return self.type == "cup"


@lru_cache(maxsize=1)
def load_competitions() -> dict[str, Competition]:
    raw = yaml.safe_load((REGISTRY_DIR / "competitions.yaml").read_text(encoding="utf-8"))
    out = {}
    for cid, c in raw["competitions"].items():
        out[cid] = Competition(
            competition_id=cid,
            name=c["name"],
            country=c["country"],
            tier=int(c["tier"]),
            type=c["type"],
            timezone=c["timezone"],
            season_style=c["season_style"],
            sources=c.get("sources", {}),
        )
    return out


def get_competition(competition_id: str) -> Competition:
    comps = load_competitions()
    if competition_id not in comps:
        raise KeyError(f"unknown competition {competition_id!r}; known: {sorted(comps)}")
    return comps[competition_id]


def season_label(start_year: int, style: str = "split") -> str:
    return str(start_year) if style == "calendar" else f"{start_year}-{start_year + 1}"


def season_start_year(label: str) -> int:
    return int(str(label)[:4])
