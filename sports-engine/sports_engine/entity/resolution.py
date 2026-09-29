"""Conservative team entity resolution.

Resolution order for a raw team name seen in a source:

1. alias already stored for this (source, country, name)          -> reused (stable ids)
2. curated registry alias (case-insensitive)                      -> REGISTRY   (1.00)
3. normalized name equal to exactly ONE known team's alias          -> NORMALIZED (0.95)
4. fixture co-occurrence: the name's fixtures (date, opponent, side)
   line up with one already-resolved team in another source        -> COOCCURRENCE
   (>= min_evidence fixtures and >= min_share agreement)
5. token-subset candidates exist but nothing above is conclusive   -> AMBIGUOUS (queued for review, NOT merged)
6. no candidate at all                                              -> NEW_ENTITY

Ambiguous names are never merged automatically; their matches stay out of the
canonical match table until a human adds an alias to the registry.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

REGISTRY_DIR = Path(__file__).parent / "registry"

STOPWORDS = {
    "fc", "ac", "as", "ss", "ssc", "us", "uc", "sc", "cf", "cfc", "bc", "acf", "afc", "ssd", "spa", "club",
    "calcio", "football", "futbol", "fbc", "sport", "sportiva", "associazione", "societa", "asd", "usd",
    "acr", "de", "del", "the", "a", "c", "r", "sv", "vfb", "vfl", "tsg", "rc", "ud", "cd", "sd", "rcd",
}

_PUNCT = re.compile(r"[^a-z0-9 ]+")


def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


@lru_cache(maxsize=65536)
def normalize_team_name(name: str) -> str:
    s = strip_accents(name).lower().replace("&", " ")
    s = _PUNCT.sub(" ", s)
    toks = [t for t in s.split() if t not in STOPWORDS and not t.isdigit()]
    return " ".join(toks)


def name_tokens(name: str) -> frozenset[str]:
    return frozenset(normalize_team_name(name).split())


def slugify(name: str) -> str:
    n = normalize_team_name(name) or strip_accents(name).lower()
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-") or "unknown"


@dataclass(frozen=True)
class TeamEntry:
    team_id: str
    name: str
    country: str
    aliases: tuple[str, ...]


@dataclass
class Resolution:
    raw_name: str
    team_id: str | None
    method: str            # EXISTING | REGISTRY | NORMALIZED | COOCCURRENCE | NEW_ENTITY | AMBIGUOUS
    confidence: float
    candidates: list[str] = field(default_factory=list)
    evidence: str | None = None


class TeamRegistry:
    def __init__(self, entries: Iterable[TeamEntry]):
        self.entries: dict[str, TeamEntry] = {}
        self.alias_index: dict[tuple[str, str], str] = {}
        for e in entries:
            if e.team_id in self.entries:
                raise ValueError(f"duplicate team id {e.team_id}")
            self.entries[e.team_id] = e
            for a in {e.name, *e.aliases}:
                k = (e.country, a.strip().lower())
                if k in self.alias_index and self.alias_index[k] != e.team_id:
                    raise ValueError(f"alias collision {a!r}: {self.alias_index[k]} vs {e.team_id}")
                self.alias_index[k] = e.team_id

    @classmethod
    def load(cls, directory: Path = REGISTRY_DIR) -> "TeamRegistry":
        entries = []
        for f in sorted(directory.glob("teams_*.yaml")):
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            country = doc["country"]
            for tid, t in doc["teams"].items():
                entries.append(TeamEntry(tid, t["name"], country, tuple(t.get("aliases", []))))
        return cls(entries)

    def lookup(self, country: str, raw: str) -> str | None:
        return self.alias_index.get((country, raw.strip().lower()))


@dataclass(frozen=True)
class FixtureObs:
    """A fixture as seen by one source (raw names), used for co-occurrence evidence."""
    match_date: date
    home: str
    away: str
    season_start_year: int


class TeamResolver:
    def __init__(
        self,
        registry: TeamRegistry,
        known_aliases: dict[tuple[str, str], str] | None = None,   # (country, alias_lower) -> team_id (any source)
        team_names: dict[str, str] | None = None,                  # team_id -> display name
        min_evidence: int = 5,
        min_share: float = 0.9,
    ):
        self.registry = registry
        self.known_aliases = dict(known_aliases or {})
        self.team_names = dict(team_names or {})
        for tid, e in registry.entries.items():
            self.team_names.setdefault(tid, e.name)
        self.min_evidence = min_evidence
        self.min_share = min_share

    # ---------------------------------------------------------------- indices
    def _norm_index(self, country: str) -> dict[str, set[str]]:
        idx: dict[str, set[str]] = {}
        for (c, alias), tid in list(self.registry.alias_index.items()) + list(self.known_aliases.items()):
            if c == country:
                idx.setdefault(normalize_team_name(alias), set()).add(tid)
        for tid, name in self.team_names.items():
            if tid.startswith(country.lower() + "-"):
                idx.setdefault(normalize_team_name(name), set()).add(tid)
        return idx

    def _token_candidates(self, country: str, raw: str) -> list[str]:
        toks = name_tokens(raw)
        if not toks:
            return []
        cands = set()
        for (c, alias), tid in list(self.registry.alias_index.items()) + list(self.known_aliases.items()):
            if c != country:
                continue
            at = name_tokens(alias)
            if at and (toks <= at or at <= toks):
                cands.add(tid)
        return sorted(cands)

    # ---------------------------------------------------------------- resolve
    def resolve_static(self, country: str, raw: str) -> Resolution:
        """Steps 2, 3 and candidate generation (no fixture evidence)."""
        tid = self.registry.lookup(country, raw)
        if tid:
            return Resolution(raw, tid, "REGISTRY", 1.0)
        tid = self.known_aliases.get((country, raw.strip().lower()))
        if tid:
            return Resolution(raw, tid, "NORMALIZED", 0.97, evidence="exact alias known from another source")
        norm = normalize_team_name(raw)
        hits = self._norm_index(country).get(norm, set()) if norm else set()
        if len(hits) == 1:
            return Resolution(raw, next(iter(hits)), "NORMALIZED", 0.95, evidence=f"normalized={norm!r}")
        if len(hits) > 1:
            return Resolution(raw, None, "AMBIGUOUS", 0.0, sorted(hits), evidence=f"normalized={norm!r}")
        cands = self._token_candidates(country, raw)
        if cands:
            return Resolution(raw, None, "AMBIGUOUS", 0.0, cands, evidence="token-subset candidates only")
        return Resolution(raw, None, "NEW_ENTITY", 0.0)

    def cooccurrence(
        self,
        raw: str,
        own_fixtures: list[FixtureObs],
        own_resolved: dict[str, str],
        reference: dict[tuple[date, str], list[tuple[str, str]]],
    ) -> Resolution | None:
        """Match ``raw`` by lining up its fixtures with already-canonical fixtures.

        ``reference`` maps (date, team_id) -> list of (opponent_team_id, side) where
        side is 'H' if team_id was at home.
        """
        votes: Counter[str] = Counter()
        considered = 0
        for fx in own_fixtures:
            if fx.home == raw and fx.away in own_resolved:
                other, side_of_raw = own_resolved[fx.away], "H"
            elif fx.away == raw and fx.home in own_resolved:
                other, side_of_raw = own_resolved[fx.home], "A"
            else:
                continue
            considered += 1
            other_side = "A" if side_of_raw == "H" else "H"
            for delta in (0, -1, 1):
                d = fx.match_date + timedelta(days=delta)
                hits = [opp for opp, side in reference.get((d, other), []) if side == other_side]
                if hits:
                    for opp in set(hits):
                        votes[opp] += 1
                    break
        if not votes:
            return None
        best, n_best = votes.most_common(1)[0]
        total = sum(votes.values())
        share = n_best / total
        ev = f"{n_best}/{total} aligned fixtures ({considered} with resolved opponent)"
        if n_best >= self.min_evidence and share >= self.min_share:
            return Resolution(raw, best, "COOCCURRENCE", round(min(0.99, share), 3), evidence=ev)
        return Resolution(raw, None, "AMBIGUOUS", 0.0, [t for t, _ in votes.most_common(5)], evidence=ev)

    def new_entity_id(self, country: str, raw: str) -> str:
        base = f"{country.lower()}-{slugify(raw)}"
        tid, n = base, 2
        while tid in self.team_names and normalize_team_name(self.team_names[tid]) != normalize_team_name(raw):
            tid = f"{base}-{n}"
            n += 1
        return tid

    def register(self, country: str, raw: str, team_id: str, name: str | None = None) -> None:
        self.known_aliases[(country, raw.strip().lower())] = team_id
        self.team_names.setdefault(team_id, name or raw)
