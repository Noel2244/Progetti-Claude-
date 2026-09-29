"""Provider adapter interface.

Every external source is wrapped by a ``DataProvider``. Providers:

* describe themselves (license, terms, reliability tier, capabilities);
* ``discover()`` the datasets (files/endpoints) relevant to a request;
* ``parse()`` raw bytes into normalized records (never leaking native formats);
* expose the common ``fetch_*`` interface backed by the immutable raw lake.

If a provider is unavailable the rest of the system keeps working.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable

from sports_engine.core.enums import DataClass, SourceTier
from sports_engine.normalization.records import ParsedDataset, SourceMatchRecord, SourceOddsRecord


@dataclass(frozen=True)
class DatasetDescriptor:
    provider: str
    dataset_key: str
    url: str | None
    kind: str                         # results | results_odds | fixtures | events | metadata
    competition_id: str | None = None
    season: str | None = None
    immutable: bool = False           # closed historical season -> never re-downloaded
    file_ext: str = "csv"


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    display_name: str
    homepage: str
    license_id: str
    license_url: str | None
    terms_url: str | None
    attribution: str | None
    source_tier: SourceTier
    data_classes: tuple[DataClass, ...]
    capabilities: tuple[str, ...]      # results, odds, closing_odds, stats, events, xg, lineups, fixtures ...
    allowed_hosts: tuple[str, ...]
    requires_opt_in: bool = False
    notes: str = ""
    restrictions: tuple[str, ...] = field(default_factory=tuple)


class DataProvider(ABC):
    info: ProviderInfo

    def __init__(self, settings=None):
        self.settings = settings

    @property
    def name(self) -> str:
        return self.info.name

    def is_enabled(self) -> bool:
        if self.settings is None:
            return True
        return bool(self.settings.get(f"providers.{self.name}.enabled", True))

    def enabled_reason(self) -> str | None:
        """None when usable; otherwise a human-readable reason."""
        return None if self.is_enabled() else "disabled in config.yaml"

    @abstractmethod
    def discover(self, competition_ids: Iterable[str], seasons: Iterable[int] | None = None) -> list[DatasetDescriptor]:
        """List the datasets relevant to the given competitions (and season start years)."""

    @abstractmethod
    def parse(self, descriptor: DatasetDescriptor, content: bytes, raw_sha256: str,
              acquired_at=None) -> ParsedDataset:
        """Parse raw bytes into normalized records."""

    def followups(self, descriptor: DatasetDescriptor, content: bytes) -> list[DatasetDescriptor]:
        """Datasets discovered from the content of another (e.g. an index file)."""
        return []

    # ------------------------------------------------------------------
    # Common interface (directive section 97). Defaults: not supported.
    # Concrete data flows through the lake + ingestion pipeline; these
    # helpers let callers ask a single provider directly.
    def fetch_competitions(self) -> list[str]:
        return []

    def fetch_matches(self, parsed: Iterable[ParsedDataset]) -> list[SourceMatchRecord]:
        return [m for ds in parsed for m in ds.matches]

    def fetch_odds(self, parsed: Iterable[ParsedDataset]) -> list[SourceOddsRecord]:
        return [o for ds in parsed for o in ds.odds]

    def fetch_events(self, *args, **kwargs):
        raise NotImplementedError(f"{self.name} does not provide events")

    def fetch_lineups(self, *args, **kwargs):
        raise NotImplementedError(f"{self.name} does not provide lineups")

    def fetch_players(self, *args, **kwargs):
        raise NotImplementedError(f"{self.name} does not provide players")

    def fetch_statistics(self, parsed: Iterable[ParsedDataset]) -> list[dict]:
        return [{"source_match_key": m.source_match_key, **m.stats} for ds in parsed for m in ds.matches if m.stats]
