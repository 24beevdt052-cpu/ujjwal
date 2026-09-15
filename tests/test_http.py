"""desk.data._http: retry classification, atomic cache writes, cached-body validation, download manifest."""

from __future__ import annotations

import json

import pytest
import requests

from desk.data import _http


class _Resp:
    def __init__(self, status: int, body: bytes = b"x" * 100):
        self.status_code, self.content = status, body


def _session(responses, calls):
    class S:
        def get(self, url, headers=None, timeout=None):
            calls.append(url)
            r = responses[min(len(calls) - 1, len(responses) - 1)]
            if isinstance(r, Exception):
                raise r
            return r

    return S()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(_http.time, "sleep", lambda s: slept.append(s))
    monkeypatch.delenv("DESK_OFFLINE", raising=False)
    return slept


def test_permanent_4xx_is_not_retried(tmp_path, _no_sleep):
    calls = []
    with pytest.raises(_http.PermanentFetchError):
        _http.fetch_cached("https://x.invalid/a", tmp_path / "a", session=_session([_Resp(403)], calls), retries=5)
    assert len(calls) == 1 and _no_sleep == []


def test_transient_errors_retry_without_sleeping_after_last_attempt(tmp_path, _no_sleep):
    calls = []
    sess = _session([_Resp(503), requests.exceptions.ConnectionError("reset"), _Resp(429)], calls)
    with pytest.raises(_http.FetchError):
        _http.fetch_cached("https://x.invalid/b", tmp_path / "b", session=sess, retries=3, backoff_s=1.0)
    assert len(calls) == 3 and _no_sleep == [1.0, 2.0]
    assert not (tmp_path / "b").exists()


def test_success_after_transient_failure_writes_cache_atomically(tmp_path):
    calls = []
    sess = _session([_Resp(500), _Resp(200, b"hello world")], calls)
    body = _http.fetch_cached("https://x.invalid/c", tmp_path / "c", session=sess, retries=3)
    assert body == b"hello world" and (tmp_path / "c").read_bytes() == b"hello world"
    assert not list(tmp_path.glob(".c.*.tmp"))


def test_invalid_cached_body_is_redownloaded_online_and_rejected_offline(tmp_path, monkeypatch):
    cache = tmp_path / "d"
    cache.write_bytes(b"<html>error page</html>")
    calls = []
    sess = _session([_Resp(200, b"OBS_VALUE,1\n" * 10)], calls)
    ok = lambda b: b.startswith(b"OBS_VALUE")  # noqa: E731
    body = _http.fetch_cached("https://x.invalid/d", cache, session=sess, validator=ok)
    assert body.startswith(b"OBS_VALUE") and len(calls) == 1
    cache.write_bytes(b"<html>error page</html>")
    monkeypatch.setenv("DESK_OFFLINE", "1")
    with pytest.raises(_http.FetchError, match="invalid"):
        _http.fetch_cached("https://x.invalid/d", cache, validator=ok)


def test_too_small_cached_body_is_not_trusted_offline(tmp_path, monkeypatch):
    cache = tmp_path / "e"
    cache.write_bytes(b"tiny")
    monkeypatch.setenv("DESK_OFFLINE", "1")
    with pytest.raises(_http.FetchError):
        _http.fetch_cached("https://x.invalid/e", cache, min_bytes=100)


def test_downloads_under_raw_are_recorded_in_the_manifest(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    monkeypatch.setattr(_http, "RAW_DIR", raw)
    monkeypatch.setattr(_http, "MANIFEST_PATH", raw / "_download_manifest.json")
    monkeypatch.setattr(_http, "_MANIFEST_LOCK", raw / ".lock")
    calls = []
    _http.fetch_cached("https://x.invalid/f", raw / "sub" / "f.html", session=_session([_Resp(200, b"abc")], calls))
    manifest = json.loads((raw / "_download_manifest.json").read_text())
    entry = manifest["sub/f.html"]
    assert entry["url"] == "https://x.invalid/f" and entry["bytes"] == 3 and entry["how"] == "download"
    assert _http.retrieval_note([raw / "sub" / "f.html"]) == f"retrieved {entry['retrieved']}"
    # caches outside data/raw (e.g. test temp dirs) are not recorded
    _http.fetch_cached("https://x.invalid/g", tmp_path / "g", session=_session([_Resp(200, b"abc")], calls))
    assert set(json.loads((raw / "_download_manifest.json").read_text())) == {"sub/f.html"}


def test_real_manifest_dates_every_cached_raw_file():
    files = [f for f in _http.RAW_DIR.rglob("*") if f.is_file() and not f.name.startswith(".")
             and f != _http.MANIFEST_PATH]
    if not files:
        pytest.skip("no data/raw cache")
    missing = {_http._raw_key(f) for f in files} - set(_http.load_manifest())
    assert not missing, sorted(missing)[:10]
