"""Cached, retrying HTTP fetch shared by every `fetch_*` module.

The build machine has an intermittently intercepted TLS path (resets, 429s), so every download retries with
exponential backoff and is cached under data/raw/. With DESK_OFFLINE=1 only the cache is used.

Why the retry / cache rules look like this:
* Only transient failures are retried (connection resets, timeouts, HTTP 429 and 5xx, a body that fails
  validation). A 403/404 will not change on retry, so it fails at once instead of burning ~90 s of backoff.
* No sleep after the last attempt — the caller gets the error immediately.
* Cache files are written to a temp file and `os.replace`d into place, so a crash never leaves a half-written body
  that later runs would trust.
* Cached bodies are re-validated (`min_bytes`, optional `validator`) on every read. A cached HTML error page is
  re-downloaded when online and raises under DESK_OFFLINE=1, instead of silently locking in a fallback forever.
* Every body written under data/raw/ is recorded in `data/raw/_download_manifest.json` (path -> url, retrieval date
  on the build machine's local calendar plus the exact UTC timestamp, sha256, bytes). Retrieval dates printed in docs and chart footers are read from this record
  (`retrieval_note`), never from a hard-coded literal, so a refreshed download changes the printed date.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import requests

from desk.paths import RAW_DIR

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
MANIFEST_PATH = RAW_DIR / "_download_manifest.json"
_MANIFEST_LOCK = RAW_DIR / ".download_manifest.lock"
_TRANSIENT_EXC = (
    requests.exceptions.ConnectionError,  # includes SSLError and connection resets
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ContentDecodingError,
)


def offline() -> bool:
    return os.environ.get("DESK_OFFLINE", "").strip() not in ("", "0", "false", "False")


class FetchError(RuntimeError):
    pass


class TransientFetchError(FetchError):
    """Worth retrying: HTTP 429/5xx or a body that failed validation."""


class PermanentFetchError(FetchError):
    """Not worth retrying: e.g. HTTP 403/404."""


# --------------------------------------------------------------------------------------------- file helpers
def atomic_write_bytes(path: Path, body: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _invalid_reason(body: bytes, min_bytes: int, validator: Callable[[bytes], bool] | None) -> str | None:
    if len(body) < min_bytes:
        return f"body too small ({len(body)} bytes < {min_bytes})"
    if validator is not None and not validator(body):
        return "body failed content validation"
    return None


# --------------------------------------------------------------------------------------------- download manifest
@contextlib.contextmanager
def _manifest_locked():
    _MANIFEST_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(_MANIFEST_LOCK, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def load_manifest() -> dict[str, dict]:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _raw_key(path: Path) -> str | None:
    try:
        return Path(path).resolve().relative_to(RAW_DIR.resolve()).as_posix()
    except ValueError:
        return None


def _write_manifest(manifest: dict) -> None:
    atomic_write_bytes(MANIFEST_PATH, (json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode())


def record_download(cache_path: Path, source: str, body: bytes, how: str = "download") -> None:
    """Record a body written under data/raw/ (no-op for caches elsewhere, e.g. test temp dirs)."""
    key = _raw_key(cache_path)
    if key is None:
        return
    with _manifest_locked():
        manifest = load_manifest()
        now = dt.datetime.now(dt.timezone.utc)
        manifest[key] = {
            "url": source,
            "retrieved": now.astimezone().date().isoformat(),
            "retrieved_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "how": how,
        }
        _write_manifest(manifest)


def backfill_manifest_from_mtime(root: Path = RAW_DIR, urls: dict[str, str] | None = None) -> int:
    """One-off: record files cached before the manifest existed, dated by their file modification time.

    Entries are marked `how = "mtime_backfill"` so nobody mistakes them for a logged download. Returns the count added.
    """
    urls = urls or {}
    added = 0
    with _manifest_locked():
        manifest = load_manifest()
        for f in sorted(Path(root).rglob("*")):
            key = _raw_key(f)
            if not f.is_file() or key is None or key in manifest or f.name.startswith(".") or f == MANIFEST_PATH:
                continue
            body = f.read_bytes()
            mtime = dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc)
            manifest[key] = {
                "url": urls.get(key, ""),
                "retrieved": mtime.astimezone().date().isoformat(),
                "retrieved_at_utc": mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
                "how": "mtime_backfill",
            }
            added += 1
        _write_manifest(manifest)
    return added


def retrieval_dates(paths: Iterable[Path]) -> list[str]:
    manifest = load_manifest()
    out = []
    for p in paths:
        key = _raw_key(Path(p))
        if key is not None and key in manifest:
            out.append(manifest[key]["retrieved"])
    return sorted(set(out))


def retrieval_note(paths: Iterable[Path]) -> str:
    """'retrieved 2026-09-16' / 'retrieved 2026-09-16 to 2026-09-20' from the manifest, for the given cache files."""
    paths = list(paths)
    dates = retrieval_dates(paths)
    if not dates:
        return "retrieval date not recorded in data/raw/_download_manifest.json"
    span = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"
    missing = len({_raw_key(Path(p)) for p in paths} - set(load_manifest())) if paths else 0
    return f"retrieved {span}" + (f" ({missing} cache files without a manifest entry)" if missing else "")


# --------------------------------------------------------------------------------------------- fetch
def cached_download(
    cache_path: Path,
    download: Callable[[], bytes],
    *,
    source: str,
    refresh: bool = False,
    retries: int = 5,
    backoff_s: float = 3.0,
    min_bytes: int = 1,
    validator: Callable[[bytes], bool] | None = None,
) -> bytes:
    """Cache-first wrapper around any `download()` callable (GET, POST with a session token, ...)."""
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        body = cache_path.read_bytes()
        reason = _invalid_reason(body, min_bytes, validator)
        if reason is None:
            return body
        if offline():
            raise FetchError(f"cached body at {cache_path} is invalid ({reason}) and DESK_OFFLINE=1 forbids re-download")
        print(f"[_http] cached body at {cache_path} is invalid ({reason}); re-downloading")
    if offline():
        raise FetchError(f"DESK_OFFLINE=1 and no cache at {cache_path}")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            body = download()
            reason = _invalid_reason(body, min_bytes, validator)
            if reason is not None:
                raise TransientFetchError(reason)
            atomic_write_bytes(cache_path, body)
            record_download(cache_path, source, body)
            return body
        except PermanentFetchError:
            raise
        except (TransientFetchError, *_TRANSIENT_EXC) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff_s * (2**attempt))
        except requests.exceptions.RequestException as e:  # invalid URL, too many redirects, ...: not transient
            raise PermanentFetchError(f"{source}: {e}") from e
    raise FetchError(f"Failed to fetch {source} after {retries} attempts: {last}")


def http_get(url: str, *, headers: dict | None = None, session: requests.Session | None = None,
             timeout_s: float = 45.0) -> bytes:
    sess = session or requests.Session()
    r = sess.get(url, headers={"User-Agent": BROWSER_UA, **(headers or {})}, timeout=timeout_s)
    if r.status_code == 429 or r.status_code >= 500:
        raise TransientFetchError(f"HTTP {r.status_code} for {url}")
    if r.status_code >= 400:
        raise PermanentFetchError(f"HTTP {r.status_code} for {url}")
    return r.content


def fetch_cached(
    url: str,
    cache_path: Path,
    *,
    refresh: bool = False,
    retries: int = 5,
    backoff_s: float = 3.0,
    timeout_s: float = 45.0,
    headers: dict | None = None,
    session: requests.Session | None = None,
    min_bytes: int = 1,
    validator: Callable[[bytes], bool] | None = None,
) -> bytes:
    """Return the body of `url`, from `cache_path` when present and valid (unless refresh), else download and cache it."""
    return cached_download(
        cache_path,
        lambda: http_get(url, headers=headers, session=session, timeout_s=timeout_s),
        source=url,
        refresh=refresh,
        retries=retries,
        backoff_s=backoff_s,
        min_bytes=min_bytes,
        validator=validator,
    )
