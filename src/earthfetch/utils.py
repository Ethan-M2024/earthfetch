"""Shared plumbing: sessions with retries, cache dir, silent streaming downloads.

The library never prints. It logs to the ``earthfetch`` logger and reports
download progress through an optional callback.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import DownloadError

logger = logging.getLogger("earthfetch")

CHUNK = 1024 * 256

#: Progress callback signature: (filename, bytes_done, bytes_total_or_0)
ProgressFn = Callable[[str, int, int], None]

_session: Optional[requests.Session] = None


def get_session() -> requests.Session:
    """Shared Session with connection pooling and retry/backoff."""
    global _session
    if _session is None:
        from . import __version__

        retry = Retry(
            total=4,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
        s = requests.Session()
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers["User-Agent"] = f"earthfetch/{__version__}"
        _session = s
    return _session


def get_cache_dir() -> Path:
    """Download cache: $EARTHFETCH_CACHE, else the platform cache dir."""
    env = os.environ.get("EARTHFETCH_CACHE")
    if env:
        return Path(env)
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "earthfetch"


def print_progress(filename: str, done: int, total: int) -> None:
    """Progress callback that writes a carriage-return line to stderr.

    Pass as ``progress=print_progress`` in CLI/script contexts.
    """
    if total:
        print(f"\r{filename}: {100 * done // total}% ({done / 1e6:.1f} MB)",
              end="", file=sys.stderr, flush=True)
        if done >= total:
            print(file=sys.stderr)
    else:
        print(f"\r{filename}: {done / 1e6:.1f} MB", end="", file=sys.stderr, flush=True)


def validate_bbox(bbox: Sequence[float]) -> Tuple[float, float, float, float]:
    """Validate (min_lon, min_lat, max_lon, max_lat) and return it as a tuple."""
    if len(bbox) != 4:
        raise ValueError("bbox must be (min_lon, min_lat, max_lon, max_lat)")
    min_lon, min_lat, max_lon, max_lat = map(float, bbox)
    if not (-180 <= min_lon < max_lon <= 180):
        raise ValueError(f"invalid longitudes: {min_lon}, {max_lon}")
    if not (-90 <= min_lat < max_lat <= 90):
        raise ValueError(f"invalid latitudes: {min_lat}, {max_lat}")
    return (min_lon, min_lat, max_lon, max_lat)


def download_file(
    url: str,
    out_dir: str | os.PathLike | None = None,
    filename: str | None = None,
    overwrite: bool = False,
    session: requests.Session | None = None,
    timeout: int = 120,
    progress: ProgressFn | None = None,
) -> Path:
    """Stream a URL to disk. Skips the download if the file already exists.

    ``out_dir`` defaults to the earthfetch cache dir. Writes to a ``.part``
    file and renames on completion, so interrupted runs never leave corrupt
    output. Verifies the byte count against Content-Length and raises
    ``DownloadError`` on truncation. Returns the local path.
    """
    out_dir = Path(out_dir) if out_dir is not None else get_cache_dir() / "downloads"
    out_dir.mkdir(parents=True, exist_ok=True)
    if filename is None:
        filename = os.path.basename(urlparse(url).path) or "download.bin"
    dest = out_dir / filename
    if dest.exists() and not overwrite:
        logger.debug("cache hit: %s", dest)
        return dest

    sess = session or get_session()
    tmp = dest.with_suffix(dest.suffix + ".part")
    logger.info("downloading %s -> %s", url, dest)
    try:
        with sess.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            done = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=CHUNK):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(filename, done, total)
    except requests.RequestException as exc:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"download failed for {url}: {exc}") from exc
    if total and done != total:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"truncated download: got {done} of {total} bytes for {url}")
    tmp.replace(dest)
    return dest
