"""ArcticDEM and REMA polar DEM mosaics from the Polar Geospatial Center.

High-resolution (2 m, 10 m, 32 m) surface models for the Arctic (ArcticDEM,
everything north of ~60°N) and Antarctica (REMA), served as COGs on AWS Open
Data and indexed by PGC's public STAC API. No key, no account.

STAC: https://stac.pgc.umn.edu/api/v1
"""

from __future__ import annotations

from collections.abc import Sequence

from .exceptions import TileNotFoundError
from .utils import get_session, logger, validate_bbox

PGC_STAC_URL = "https://stac.pgc.umn.edu/api/v1/search"

#: (region, resolution) -> STAC collection id
POLAR_COLLECTIONS = {
    ("arcticdem", "2m"): "arcticdem-mosaics-v4.1-2m",
    ("arcticdem", "10m"): "arcticdem-mosaics-v4.1-10m",
    ("arcticdem", "32m"): "arcticdem-mosaics-v4.1-32m",
    ("rema", "2m"): "rema-mosaics-v2.0-2m",
    ("rema", "10m"): "rema-mosaics-v2.0-10m",
    ("rema", "32m"): "rema-mosaics-v2.0-32m",
}

#: native pixel size (m) per resolution key
POLAR_NATIVE_M = {"2m": 2.0, "10m": 10.0, "32m": 32.0}


def polar_region(bbox: Sequence[float]) -> str:
    """'arcticdem' for a northern-hemisphere bbox, 'rema' for a southern one."""
    _, min_lat, _, max_lat = validate_bbox(bbox)
    return "arcticdem" if (min_lat + max_lat) / 2 >= 0 else "rema"


def _polar_resolution(resolution: str) -> str:
    res = str(resolution).lower()
    if res not in POLAR_NATIVE_M:
        raise ValueError(
            f"polar DEMs come in {sorted(POLAR_NATIVE_M)}; got {resolution!r}"
        )
    return res


def search_polar_dem(
    bbox: Sequence[float],
    resolution: str = "10m",
    region: str = "auto",
    limit: int = 500,
) -> list[dict]:
    """STAC items of the ArcticDEM/REMA mosaic tiles covering a bbox.

    Parameters
    ----------
    bbox : (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees.
    resolution : "2m", "10m", or "32m".
    region : "arcticdem", "rema", or "auto" (picked by hemisphere).
    limit : maximum items to return (follows STAC paging).
    """
    bbox = validate_bbox(bbox)
    res = _polar_resolution(resolution)
    region = polar_region(bbox) if region == "auto" else region.lower()
    if (region, res) not in POLAR_COLLECTIONS:
        raise ValueError(f"unknown polar region {region!r}; use 'arcticdem' or 'rema'")
    body = {
        "collections": [POLAR_COLLECTIONS[(region, res)]],
        "bbox": list(bbox),
        "limit": min(limit, 100),
    }
    session = get_session()
    items: list[dict] = []
    url, method = PGC_STAC_URL, "POST"
    while url and len(items) < limit:
        if method == "POST":
            resp = session.post(url, json=body, timeout=60)
        else:
            resp = session.get(url, timeout=60)
        resp.raise_for_status()
        page = resp.json()
        items.extend(page.get("features", []))
        nxt = next((ln for ln in page.get("links", []) if ln.get("rel") == "next"), None)
        if not nxt or not page.get("features"):
            break
        url = nxt["href"]
        method = nxt.get("method", "GET").upper()
        if method == "POST":
            body = nxt.get("body", body)
    logger.info("PGC: %d %s %s tile(s) for %s", len(items), region, res, tuple(bbox))
    return items[:limit]


def polar_dem_urls(
    bbox: Sequence[float], resolution: str = "10m", region: str = "auto"
) -> list[str]:
    """COG URLs of the ArcticDEM/REMA mosaic tiles covering a bbox.

    Raises ``TileNotFoundError`` outside the polar mosaics' coverage.
    """
    items = search_polar_dem(bbox, resolution=resolution, region=region)
    urls = [it["assets"]["dem"]["href"] for it in items if "dem" in it.get("assets", {})]
    if not urls:
        raise TileNotFoundError(
            f"no ArcticDEM/REMA {resolution} tiles cover {tuple(bbox)} — the "
            "polar mosaics cover roughly north of 60°N and Antarctica; use "
            "source='auto' elsewhere"
        )
    return urls
