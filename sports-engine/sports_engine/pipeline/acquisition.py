"""HistoricalDataAcquisitionPipeline: discover -> download -> hash -> preserve -> manifest.

* immutable (closed-season) datasets already in the lake are never re-downloaded;
* mutable datasets use conditional requests (ETag / Last-Modified);
* one worker per provider (parallel across providers, strictly serial per host);
* a failing provider is recorded and skipped - the others continue;
* missing upstream files (404) are recorded as coverage gaps.
"""

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sports_engine.core.config import Settings
from sports_engine.core.errors import DatasetNotFoundError, ProviderError, RobotsDisallowedError
from sports_engine.core.logging import get_logger, log_event
from sports_engine.core.timeutils import iso, utcnow
from sports_engine.data.download import PoliteDownloader
from sports_engine.data.lake import RawDataLake
from sports_engine.providers.base import DataProvider, DatasetDescriptor
from sports_engine.providers.registry import get_provider

log = get_logger("acquisition")


@dataclass
class ProviderAcquisition:
    provider: str
    status: str = "OK"                   # OK | DISABLED | DEGRADED | UNAVAILABLE
    reason: str | None = None
    discovered: int = 0
    downloaded: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)


def descriptor_meta(d: DatasetDescriptor) -> dict:
    return {"kind": d.kind, "competition_id": d.competition_id, "season": d.season,
            "immutable": d.immutable, "file_ext": d.file_ext}


def descriptor_from_entry(entry) -> DatasetDescriptor:
    ex = entry.extra or {}
    return DatasetDescriptor(
        provider=entry.provider,
        dataset_key=entry.dataset_key,
        url=entry.url,
        kind=ex.get("kind", "results"),
        competition_id=ex.get("competition_id"),
        season=ex.get("season"),
        immutable=bool(ex.get("immutable", False)),
        file_ext=ex.get("file_ext", entry.stored_path.rsplit(".", 1)[-1]),
    )


class HistoricalDataAcquisitionPipeline:
    def __init__(self, settings: Settings, lake: RawDataLake | None = None, downloader: PoliteDownloader | None = None):
        self.settings = settings
        self.lake = lake or RawDataLake(settings.data_dir)
        self._downloader = downloader

    def _make_downloader(self, providers: list[DataProvider]) -> PoliteDownloader:
        if self._downloader is not None:
            return self._downloader
        hosts: set[str] = set()
        intervals: dict[str, float] = {}
        for p in providers:
            for h in p.info.allowed_hosts:
                hosts.add(h)
                intervals[h] = max(intervals.get(h, 0.0), float(self.settings.get(f"providers.{p.name}.min_interval_seconds", 1.0)))
        return PoliteDownloader(
            user_agent=self.settings.get("http.user_agent"),
            cache_dir=self.settings.data_dir / "metadata" / "download_cache",
            allowed_hosts=hosts,
            min_interval=intervals,
            respect_robots=bool(self.settings.get("http.respect_robots_txt", True)),
            timeout=float(self.settings.get("http.timeout_seconds", 60)),
            max_retries=int(self.settings.get("http.max_retries", 4)),
            max_bytes=int(self.settings.get("http.max_download_mb", 250)) * 1024 * 1024,
        )

    def run(self, provider_names: list[str], competitions: list[str], seasons: list[int] | None = None,
            force: bool = False) -> list[ProviderAcquisition]:
        providers = [get_provider(n, self.settings) for n in provider_names]
        usable = [p for p in providers if p.enabled_reason() is None]
        downloader = self._make_downloader(usable) if usable else None
        reports: list[ProviderAcquisition] = []
        for p in providers:
            reason = p.enabled_reason()
            if reason:
                reports.append(ProviderAcquisition(p.name, status="DISABLED", reason=reason))
        with ThreadPoolExecutor(max_workers=max(1, len(usable))) as pool:
            futures = [pool.submit(self._run_provider, p, downloader, competitions, seasons, force) for p in usable]
            reports.extend(f.result() for f in futures)
        for r in reports:
            log_event(log, "acquisition", **{k: (len(v) if isinstance(v, list) else v) for k, v in asdict(r).items()})
        return reports

    def _run_provider(self, p: DataProvider, downloader: PoliteDownloader, competitions, seasons, force) -> ProviderAcquisition:
        rep = ProviderAcquisition(p.name)
        try:
            queue = list(p.discover(competitions, seasons))
        except Exception as exc:  # provider failure must not crash the system
            rep.status, rep.reason = "UNAVAILABLE", f"discover failed: {exc}"
            return rep
        seen: set[str] = set()
        while queue:
            d = queue.pop(0)
            if d.dataset_key in seen:
                continue
            seen.add(d.dataset_key)
            rep.discovered += 1
            latest = self.lake.latest(p.name, d.dataset_key)
            content: bytes | None = None
            try:
                if latest is not None and d.immutable and not force:
                    rep.cached.append(d.dataset_key)
                    content = self.lake.read(latest)
                else:
                    res = downloader.fetch(
                        d.url,
                        etag=None if force or latest is None else (latest.etag or None),
                        last_modified=None if force or latest is None else latest.source_last_modified,
                    )
                    if res.not_modified and latest is not None:
                        rep.unchanged.append(d.dataset_key)
                        content = self.lake.read(latest)
                    else:
                        content = res.content or b""
                        before = latest.sha256 if latest else None
                        entry = self.lake.store_bytes(
                            p.name, d.dataset_key, content, d.file_ext,
                            url=d.url, etag=res.etag, source_last_modified=res.last_modified,
                            content_type=res.headers.get("Content-Type") or res.headers.get("content-type"),
                            license_id=p.info.license_id, terms_ref=p.info.terms_url,
                            extra=descriptor_meta(d),
                        )
                        (rep.unchanged if before == entry.sha256 else rep.downloaded).append(d.dataset_key)
            except DatasetNotFoundError:
                rep.missing.append(d.dataset_key)
                continue
            except RobotsDisallowedError as exc:
                rep.failed.append({"dataset": d.dataset_key, "error": str(exc)})
                rep.status, rep.reason = "UNAVAILABLE", "robots.txt disallows access; never bypassed"
                break
            except ProviderError as exc:
                rep.failed.append({"dataset": d.dataset_key, "error": str(exc)})
                rep.status = "DEGRADED"
                continue
            if content is not None:
                try:
                    queue.extend(p.followups(d, content))
                except Exception as exc:
                    rep.failed.append({"dataset": d.dataset_key, "error": f"followups: {exc}"})
        if rep.failed and rep.status == "OK":
            rep.status = "DEGRADED"
        return rep

    # ----------------------------------------------------------- manual import
    def import_inbox(self) -> list[dict]:
        """Move user-provided files from data/inbox into the immutable lake."""
        inbox = Path(self.settings.path("providers.local_csv.inbox", "data/inbox"))
        inbox.mkdir(parents=True, exist_ok=True)
        done_dir = inbox / "_imported"
        imported = []
        candidates = [(f, "local_csv") for f in sorted(inbox.glob("*.csv"))]
        candidates += [(f, "football_data") for f in sorted((inbox / "football_data").glob("*.csv"))] if (inbox / "football_data").exists() else []
        for f, provider in candidates:
            stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in f.stem)
            if provider == "local_csv":
                kind = "odds" if f.name.lower().startswith("odds") else "results"
                key = f"manual/{kind}/{stem}"
                extra = {"kind": kind, "competition_id": None, "season": None, "immutable": True, "file_ext": "csv"}
            else:
                key = f"manual/{stem}"
                extra = {"kind": "results_odds", "competition_id": None, "season": None, "immutable": True, "file_ext": "csv"}
            entry = self.lake.store_file(provider, key, f, "csv", url=None, acquisition="manual_import",
                                         downloaded_at=iso(utcnow()), extra=extra,
                                         license_id="user-provided" if provider == "local_csv" else "Football-Data-Private-Use")
            done_dir.mkdir(exist_ok=True)
            shutil.move(str(f), str(done_dir / f"{entry.sha256[:12]}_{f.name}"))
            imported.append({"file": f.name, "provider": provider, "dataset_key": key, "sha256": entry.sha256})
        return imported
