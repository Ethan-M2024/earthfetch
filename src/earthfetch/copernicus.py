"""Copernicus GLO-30 global DEM on AWS Open Data (no API key required).

30 m resolution, worldwide coverage, one COG per 1x1 degree tile.
Bucket: https://copernicus-dem-30m.s3.amazonaws.com
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Sequence

from .exceptions import TileNotFoundError
from .utils import ProgressFn, download_file, get_session, logger, validate_bbox

COP_BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"


def _tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"


def copernicus_dem_urls(bbox: Sequence[float]) -> List[str]:
    """COG URLs for GLO-30 tiles covering a bbox. Ocean-only tiles are
    absent from the bucket and are silently skipped (checked via HEAD).

    Raises ``TileNotFoundError`` when no tile exists (open ocean).
    """
    min_lon, min_lat, max_lon, max_lat = validate_bbox(bbox)
    session = get_session()
    urls = []
    for lat in range(math.floor(min_lat), math.ceil(max_lat)):
        for lon in range(math.floor(min_lon), math.ceil(max_lon)):
            name = _tile_name(lat, lon)
            url = f"{COP_BUCKET}/{name}/{name}.tif"
            if session.head(url, timeout=30).status_code == 200:
                urls.append(url)
            else:
                logger.debug("no GLO-30 tile at %s (ocean?)", name)
    if not urls:
        raise TileNotFoundError(f"no Copernicus GLO-30 tiles cover {tuple(bbox)}")
    logger.info("Copernicus: %d tile(s) for bbox %s", len(urls), tuple(bbox))
    return urls


def download_copernicus_dem(
    bbox: Sequence[float],
    out_dir: str | os.PathLike | None = None,
    overwrite: bool = False,
    workers: int = 4,
    progress: ProgressFn | None = None,
) -> List[Path]:
    """Download GLO-30 tiles covering a bbox. Returns local paths."""
    urls = copernicus_dem_urls(bbox)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(download_file, url, out_dir=out_dir,
                        overwrite=overwrite, progress=progress)
            for url in urls
        ]
        return [f.result() for f in futures]
