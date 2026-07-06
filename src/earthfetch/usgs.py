"""USGS 3DEP DEM access via The National Map API (no API key required).

API docs: https://tnmaccess.nationalmap.gov/api/v1/docs
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .exceptions import TileNotFoundError
from .utils import ProgressFn, download_file, get_session, logger, validate_bbox

TNM_URL = "https://tnmaccess.nationalmap.gov/api/v1/products"

#: Friendly resolution names -> TNM dataset names
DEM_DATASETS = {
    "1m": "Digital Elevation Model (DEM) 1 meter",
    "10m": "National Elevation Dataset (NED) 1/3 arc-second",
    "30m": "National Elevation Dataset (NED) 1 arc-second",
    "5m-ak": "Alaska IFSAR 5 meter DEM",
}


def search_dem(
    bbox: Sequence[float],
    resolution: str = "10m",
    max_items: int = 100,
) -> list[dict]:
    """Find 3DEP DEM tiles intersecting a bbox.

    Parameters
    ----------
    bbox : (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees.
    resolution : one of ``DEM_DATASETS`` keys ("1m", "10m", "30m", "5m-ak").
    max_items : cap on returned tiles.

    Returns
    -------
    list of dict
        Product dicts with ``title``, ``downloadURL``, ``sizeInBytes``,
        ``boundingBox`` and other TNM metadata.
    """
    if resolution not in DEM_DATASETS:
        raise ValueError(f"resolution must be one of {sorted(DEM_DATASETS)}")
    bbox = validate_bbox(bbox)

    session = get_session()
    items: list[dict] = []
    offset = 0
    while len(items) < max_items:
        params = {
            "datasets": DEM_DATASETS[resolution],
            "bbox": ",".join(str(v) for v in bbox),
            "prodFormats": "GeoTIFF",
            "outputFormat": "JSON",
            "max": min(100, max_items - len(items)),
            "offset": offset,
        }
        resp = session.get(TNM_URL, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("items", [])
        items.extend(batch)
        offset += len(batch)
        if not batch or offset >= data.get("total", 0):
            break
    logger.info("TNM: %d %s tile(s) for bbox %s", len(items), resolution, bbox)
    return items[:max_items]


def dem_tile_urls(
    bbox: Sequence[float],
    resolution: str = "10m",
    max_items: int = 100,
) -> list[str]:
    """Direct GeoTIFF URLs for tiles covering a bbox (newest tile per area).

    USGS republishes tiles; when several products share a title prefix the
    newest is kept, so windowed readers don't fetch duplicate coverage.
    """
    products = search_dem(bbox, resolution=resolution, max_items=max_items)
    newest: dict = {}
    for prod in sorted(products, key=lambda p: p.get("publicationDate", "")):
        url = prod.get("downloadURL")
        if not url:
            continue
        # e.g. "USGS 1/3 Arc Second n41w112 20220510" -> key "n41w112"
        key = " ".join(prod.get("title", url).split()[:-1]) or url
        newest[key] = url
    return list(newest.values())


def download_dem(
    bbox: Sequence[float],
    resolution: str = "10m",
    out_dir: str | os.PathLike | None = None,
    max_items: int = 100,
    overwrite: bool = False,
    workers: int = 4,
    progress: ProgressFn | None = None,
) -> list[Path]:
    """Download DEM tiles covering a bbox in parallel. Returns local paths.

    Tiles already on disk are skipped, so calls are resumable. ``out_dir``
    defaults to the earthfetch cache. Raises ``TileNotFoundError`` when no
    tiles cover the bbox (e.g. outside the US — try Copernicus instead).
    """
    urls = dem_tile_urls(bbox, resolution=resolution, max_items=max_items)
    if not urls:
        raise TileNotFoundError(
            f"no USGS {resolution} DEM tiles cover {tuple(bbox)}; "
            "USGS covers the US only — try load_dem(source='copernicus')"
        )
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(download_file, url, out_dir=out_dir,
                        overwrite=overwrite, progress=progress)
            for url in urls
        ]
        return [f.result() for f in futures]
