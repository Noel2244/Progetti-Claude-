from __future__ import annotations

import os
import stat

import pytest
import requests

from sports_engine.core.errors import (
    DatasetNotFoundError,
    ImmutableRecordError,
    ProviderError,
    RobotsDisallowedError,
)
from sports_engine.core.hashing import sha256_bytes
from sports_engine.data.download import PoliteDownloader
from sports_engine.data.lake import RawDataLake, safe_key


def test_lake_is_content_addressed_and_immutable(tmp_path):
    lake = RawDataLake(tmp_path)
    e1 = lake.store_bytes("prov", "a/b", b"hello", "csv", url="https://x/y")
    e2 = lake.store_bytes("prov", "a/b", b"hello", "csv", url="https://x/y")
    assert e1.sha256 == e2.sha256 == sha256_bytes(b"hello")
    assert len(lake.history("prov", "a/b")) == 1            # identical content is stored once
    e3 = lake.store_bytes("prov", "a/b", b"hello v2", "csv")
    assert len(lake.history("prov", "a/b")) == 2 and lake.latest("prov", "a/b").sha256 == e3.sha256
    path = tmp_path / e1.stored_path
    assert path.exists() and not os.access(path, os.W_OK) or os.geteuid() == 0
    assert lake.read(e1) == b"hello" and lake.verify() == []


def test_lake_detects_tampering(tmp_path):
    lake = RawDataLake(tmp_path)
    e = lake.store_bytes("prov", "k", b"data", "csv")
    p = tmp_path / e.stored_path
    os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)
    p.write_bytes(b"tampered")
    assert lake.verify()
    with pytest.raises(ImmutableRecordError):
        lake.read(e)


@pytest.mark.parametrize("key", ["../etc", "/abs", "a/../../b", "", "a//b", "a b"])
def test_unsafe_keys_rejected(key):
    with pytest.raises(ValueError):
        safe_key(key)


class FakeResp:
    def __init__(self, status, content=b"", headers=None, url="https://ok.test/f.csv", text=""):
        self.status_code = status
        self._content = content
        self.headers = headers or {}
        self.url = url
        self.text = text

    def iter_content(self, chunk_size=1):
        yield self._content


class FakeSession:
    def __init__(self, responses, robots="User-agent: *\nDisallow:\n"):
        self.responses = list(responses)
        self.robots = robots
        self.calls = []

    def get(self, url, headers=None, timeout=None, stream=False, allow_redirects=True):
        self.calls.append((url, dict(headers or {})))
        if url.endswith("/robots.txt"):
            return FakeResp(200, text=self.robots, url=url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(session, **kw):
    clock = {"t": 0.0}
    slept = []

    def sleep(s):
        slept.append(s)
        clock["t"] += s

    d = PoliteDownloader("test-agent/1.0", kw.pop("cache", "/tmp/claude-dl-test"), allowed_hosts={"ok.test"},
                         session=session, sleep=sleep, clock=lambda: clock["t"], **kw)
    return d, slept


def test_retries_then_succeeds(tmp_path):
    s = FakeSession([FakeResp(503), requests.ConnectionError("boom"), FakeResp(200, b"abc")])
    d, slept = make(s, cache=tmp_path, max_retries=4)
    r = d.fetch("https://ok.test/f.csv")
    assert r.content == b"abc" and len(slept) >= 2


def test_rate_limit_between_requests(tmp_path):
    s = FakeSession([FakeResp(200, b"a"), FakeResp(200, b"b")])
    d, slept = make(s, cache=tmp_path, min_interval={"ok.test": 3.0})
    d.fetch("https://ok.test/1.csv")
    d.fetch("https://ok.test/2.csv")
    assert any(x >= 2.9 for x in slept)


def test_robots_disallow_is_respected(tmp_path):
    s = FakeSession([FakeResp(200, b"x")], robots="User-agent: test-agent\nDisallow: /\n")
    d, _ = make(s, cache=tmp_path)
    with pytest.raises(RobotsDisallowedError):
        d.fetch("https://ok.test/f.csv")


def test_not_modified_and_not_found(tmp_path):
    s = FakeSession([FakeResp(304), FakeResp(404)])
    d, _ = make(s, cache=tmp_path)
    r = d.fetch("https://ok.test/f.csv", etag='"abc"')
    assert r.not_modified and s.calls[-1][1]["If-None-Match"] == '"abc"'
    with pytest.raises(DatasetNotFoundError):
        d.fetch("https://ok.test/g.csv")


def test_ssrf_guards(tmp_path):
    s = FakeSession([FakeResp(200, b"x", url="https://evil.test/f.csv")])
    d, _ = make(s, cache=tmp_path)
    with pytest.raises(ProviderError):
        d.fetch("file:///etc/passwd")
    with pytest.raises(ProviderError):
        d.fetch("https://notallowed.test/x")
    with pytest.raises(ProviderError):
        d.fetch("https://ok.test/f.csv")          # redirected off the allow-list


def test_browser_user_agent_refused(tmp_path):
    with pytest.raises(ValueError):
        PoliteDownloader("Mozilla/5.0", tmp_path)


def test_size_cap(tmp_path):
    s = FakeSession([FakeResp(200, b"x" * 100)])
    d, _ = make(s, cache=tmp_path, max_bytes=10, max_retries=0)
    with pytest.raises(ProviderError):
        d.fetch("https://ok.test/f.csv")
