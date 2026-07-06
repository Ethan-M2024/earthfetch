"""Sentinel-2 L2A access via the Earth Search STAC API on AWS (no API key).

Data: Cloud-Optimized GeoTIFFs in the public ``sentinel-cogs`` S3 bucket.
API:  https://earth-search.aws.element84.com/v1
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .exceptions import BandNotFoundError, NoScenesError
from .utils import ProgressFn, download_file, get_session, logger, validate_bbox

STAC_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"

#: ESA band ids -> Earth Search asset keys
BAND_ALIASES = {
    "B01": "coastal",
    "B02": "blue",
    "B03": "green",
    "B04": "red",
    "B05": "rededge1",
    "B06": "rededge2",
    "B07": "rededge3",
    "B08": "nir",
    "B8A": "nir08",
    "B09": "nir09",
    "B11": "swir16",
    "B12": "swir22",
    "SCL": "scl",
    "TCI": "visual",
}

#: Native ground resolution (m) per ESA band id
BAND_RESOLUTION = {
    "B01": 60, "B02": 10, "B03": 10, "B04": 10, "B05": 20, "B06": 20,
    "B07": 20, "B08": 10, "B8A": 20, "B09": 60, "B11": 20, "B12": 20,
    "SCL": 20, "TCI": 10,
}


def _asset_key(band: str) -> str:
    return BAND_ALIASES.get(band.upper(), band.lower())


def band_url(item: dict, band: str) -> str:
    """COG URL for one band of a STAC item (for windowed/remote reads)."""
    key = _asset_key(band)
    assets = item["assets"]
    if key not in assets:
        raise BandNotFoundError(
            f"band {band!r} (asset {key!r}) not in scene {item.get('id')}; "
            f"available: {sorted(assets)}"
        )
    return assets[key]["href"]


def scale_offset(item: dict, band: str) -> tuple:
    """(scale, offset) converting a band's DNs to surface reflectance.

    Read from the STAC ``raster:bands`` metadata when present (baseline
    >= 04.00 scenes carry offset -0.1); older scenes fall back to 1e-4, 0.
    Non-reflectance assets (SCL, TCI) return (1, 0).
    """
    key = _asset_key(band)
    if key in ("scl", "visual", "thumbnail"):
        return (1.0, 0.0)
    raster_bands = item["assets"].get(key, {}).get("raster:bands") or []
    if raster_bands:
        rb = raster_bands[0]
        return (rb.get("scale", 1e-4), rb.get("offset", 0.0))
    return (1e-4, 0.0)


def search_sentinel2(
    bbox: Sequence[float],
    start: str,
    end: str,
    max_cloud: float = 20.0,
    limit: int = 50,
) -> list[dict]:
    """Search Sentinel-2 L2A scenes.

    Parameters
    ----------
    bbox : (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees.
    start, end : ISO dates, e.g. "2026-05-01" / "2026-06-01".
    max_cloud : maximum scene cloud cover percent.
    limit : cap on returned scenes.

    Returns
    -------
    list of dict
        STAC item dicts sorted by cloud cover (clearest first). Each has
        ``id``, ``properties`` (datetime, eo:cloud_cover, ...) and ``assets``.
    """
    bbox = validate_bbox(bbox)
    session = get_session()
    body = {
        "collections": [COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": min(limit, 100),
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
    }
    items: list[dict] = []
    while len(items) < limit:
        resp = session.post(STAC_URL, json=body, timeout=60)
        resp.raise_for_status()
        page = resp.json()
        items.extend(page.get("features", []))
        nxt = next(
            (lnk for lnk in page.get("links", []) if lnk.get("rel") == "next"), None
        )
        if nxt is None or not page.get("features"):
            break
        body = nxt.get("body", body)
    items = items[:limit]
    items.sort(key=lambda i: i["properties"].get("eo:cloud_cover", 100))
    logger.info("Earth Search: %d scene(s) %s..%s cloud<%s%%",
                len(items), start, end, max_cloud)
    return items


def clearest_scene(
    bbox: Sequence[float], start: str, end: str, max_cloud: float = 20.0
) -> dict:
    """The least-cloudy scene in a date range, or raise ``NoScenesError``."""
    items = search_sentinel2(bbox, start, end, max_cloud=max_cloud, limit=50)
    if not items:
        raise NoScenesError(
            f"no Sentinel-2 scenes for {tuple(bbox)} in {start}..{end} "
            f"with cloud < {max_cloud}% — widen dates or raise max_cloud"
        )
    return items[0]


def download_sentinel2(
    item: dict,
    bands: Sequence[str] = ("B04", "B03", "B02"),
    out_dir: str | os.PathLike | None = None,
    overwrite: bool = False,
    workers: int = 4,
    progress: ProgressFn | None = None,
) -> dict[str, Path]:
    """Download selected bands of one STAC item as GeoTIFFs, in parallel.

    ``bands`` accepts ESA ids ("B04", "B08", "TCI", "SCL") or Earth Search
    asset keys ("red", "nir", "visual"). Files land in
    ``out_dir/<scene id>/`` (cache dir by default). Returns {band: path}.
    """
    from .utils import get_cache_dir

    root = Path(out_dir) if out_dir is not None else get_cache_dir() / "downloads"
    base = root / item["id"]
    urls = {band: band_url(item, band) for band in bands}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            band: pool.submit(download_file, url, out_dir=base,
                              overwrite=overwrite, progress=progress)
            for band, url in urls.items()
        }
        return {band: fut.result() for band, fut in futures.items()}


def scene_summary(item: dict) -> dict:
    """Compact one-line view of a STAC item, handy for picking scenes."""
    p = item["properties"]
    return {
        "id": item["id"],
        "date": p.get("datetime", "")[:10],
        "cloud_pct": round(p.get("eo:cloud_cover", -1), 1),
        "tile": p.get("grid:code", ""),
    }
