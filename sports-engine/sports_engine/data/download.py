"""Polite, resumable HTTP downloader.

Guarantees
----------
* honest User-Agent (never impersonates a browser or another crawler);
* robots.txt is honoured; a disallow is never bypassed;
* per-host minimum interval between requests (rate limiting) and a per-host
  lock, so parallel downloads never hammer one provider;
* retries with exponential backoff for transient failures, honouring Retry-After;
* conditional requests (ETag / Last-Modified) so unchanged files are not re-sent;
* resumable downloads through ``.part`` files + HTTP Range where supported;
* only http(s) URLs on an explicit host allow-list (basic SSRF protection);
* a hard size cap.
"""

from __future__ import annotations

import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from sports_engine.core.errors import DatasetNotFoundError, ProviderError, RobotsDisallowedError
from sports_engine.core.hashing import sha256_bytes
from sports_engine.core.logging import get_logger, log_event

log = get_logger("download")

RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    status: int
    content: bytes | None
    headers: dict[str, str] = field(default_factory=dict)
    not_modified: bool = False
    final_url: str | None = None

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag") or self.headers.get("ETag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("last-modified") or self.headers.get("Last-Modified")


class PoliteDownloader:
    def __init__(
        self,
        user_agent: str,
        cache_dir: str | Path,
        allowed_hosts: set[str] | None = None,
        min_interval: dict[str, float] | None = None,
        default_interval: float = 1.0,
        respect_robots: bool = True,
        timeout: float = 60.0,
        max_retries: int = 4,
        max_bytes: int = 250 * 1024 * 1024,
        session: Any | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        if not user_agent or "mozilla" in user_agent.lower():
            raise ValueError("an honest, non-browser user agent is required")
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_hosts = {h.lower() for h in (allowed_hosts or set())}
        self.min_interval = {k.lower(): v for k, v in (min_interval or {}).items()}
        self.default_interval = default_interval
        self.respect_robots = respect_robots
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_bytes = max_bytes
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._host_locks: dict[str, threading.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._global = threading.Lock()

    # --------------------------------------------------------------- policies
    def _check_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ProviderError(f"scheme not allowed: {url}")
        host = (parsed.hostname or "").lower()
        if not host:
            raise ProviderError(f"no host in url: {url}")
        if self.allowed_hosts and host not in self.allowed_hosts:
            raise ProviderError(f"host not on allow-list: {host}")
        return host

    def _lock_for(self, host: str) -> threading.Lock:
        with self._global:
            return self._host_locks.setdefault(host, threading.Lock())

    def _throttle(self, host: str) -> None:
        interval = self.min_interval.get(host, self.default_interval)
        last = self._last_request.get(host)
        if last is not None:
            wait = interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._clock()

    def robots_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                resp = self.session.get(
                    f"{base}/robots.txt",
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    self._robots[base] = rp
                elif resp.status_code in (401, 403):
                    # access to robots.txt denied -> treat as full disallow (conservative)
                    rp.parse(["User-agent: *", "Disallow: /"])
                    self._robots[base] = rp
                else:
                    self._robots[base] = None  # no robots.txt -> allowed
            except requests.RequestException:
                self._robots[base] = None
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    # ----------------------------------------------------------------- fetch
    def fetch(self, url: str, etag: str | None = None, last_modified: str | None = None) -> FetchResult:
        host = self._check_url(url)
        with self._lock_for(host):
            if not self.robots_allowed(url):
                raise RobotsDisallowedError(f"robots.txt disallows {url} for our user agent")
            part = self.cache_dir / (sha256_bytes(url.encode())[:32] + ".part")
            attempt = 0
            while True:
                attempt += 1
                self._throttle(host)
                # identity encoding keeps Range offsets meaningful for resumable downloads
                headers = {"User-Agent": self.user_agent, "Accept-Encoding": "identity"}
                if etag:
                    headers["If-None-Match"] = etag
                if last_modified:
                    headers["If-Modified-Since"] = last_modified
                offset = part.stat().st_size if part.exists() else 0
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                try:
                    resp = self.session.get(url, headers=headers, timeout=self.timeout, stream=True, allow_redirects=True)
                except requests.RequestException as exc:
                    if attempt > self.max_retries:
                        raise ProviderError(f"network failure for {url}: {exc}") from exc
                    self._backoff(attempt, None, url, str(exc))
                    continue
                final_url = getattr(resp, "url", url) or url
                if self.allowed_hosts and (urlparse(final_url).hostname or "").lower() not in self.allowed_hosts:
                    raise ProviderError(f"redirected to a host outside the allow-list: {final_url}")
                status = resp.status_code
                resp_headers = {k: v for k, v in resp.headers.items()}
                if status == 304:
                    return FetchResult(url, status, None, resp_headers, not_modified=True, final_url=getattr(resp, "url", url))
                if status in RETRY_STATUS:
                    if attempt > self.max_retries:
                        raise ProviderError(f"HTTP {status} for {url} after {attempt} attempts")
                    self._backoff(attempt, resp_headers.get("Retry-After"), url, f"HTTP {status}")
                    continue
                if status == 416 and offset:
                    part.unlink(missing_ok=True)
                    continue
                if status in (404, 410):
                    raise DatasetNotFoundError(f"HTTP {status} for {url}")
                if status not in (200, 206):
                    raise ProviderError(f"HTTP {status} for {url}")
                mode = "ab" if (status == 206 and offset) else "wb"
                written = offset if mode == "ab" else 0
                try:
                    with open(part, mode) as fh:
                        for chunk in resp.iter_content(chunk_size=1 << 16):
                            if not chunk:
                                continue
                            written += len(chunk)
                            if written > self.max_bytes:
                                raise ProviderError(f"download exceeds size cap ({self.max_bytes} bytes): {url}")
                            fh.write(chunk)
                except requests.RequestException as exc:
                    # keep the .part file: next attempt resumes via Range
                    if attempt > self.max_retries:
                        raise ProviderError(f"interrupted download for {url}: {exc}") from exc
                    self._backoff(attempt, None, url, f"interrupted: {exc}")
                    continue
                content = part.read_bytes()
                part.unlink(missing_ok=True)
                log_event(log, "downloaded", url=url, bytes=len(content), status=status)
                return FetchResult(url, 200, content, resp_headers, final_url=getattr(resp, "url", url))

    def _backoff(self, attempt: int, retry_after: str | None, url: str, reason: str) -> None:
        delay = min(60.0, 2.0 ** attempt)
        if retry_after:
            try:
                delay = min(300.0, max(delay, float(retry_after)))
            except ValueError:
                pass
        log_event(log, "retrying", url=url, attempt=attempt, delay=delay, reason=reason)
        self._sleep(delay)
