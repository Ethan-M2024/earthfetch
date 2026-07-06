"""NAIP aerial imagery (0.6-1 m, US) via Microsoft Planetary Computer.

Google-Earth-quality natural-color aerial photos, free, no account.
Access uses anonymous short-lived SAS tokens fetched automatically.

STAC: https://planetarycomputer.microsoft.com/api/stac/v1 (collection "naip")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray

import time
from collections.abc import Sequence

from .exceptions import TileNotFoundError
from .utils import get_session, logger

PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/naip"

#: NAIP band order in the 4-band COG
NAIP_BANDS = {"R": 1, "G": 2, "B": 3, "N": 4}

_token: dict = {"value": None, "expires": 0.0}


def _sas_token() -> str:
    """Anonymous SAS token for the NAIP blob container, cached until expiry."""
    if _token["value"] is None or time.time() > _token["expires"] - 300:
        resp = get_session().get(PC_TOKEN_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        _token["value"] = data["token"]
        expiry = data.get("msft:expiry", "")
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            _token["expires"] = dt.timestamp()
        except ValueError:
            _token["expires"] = time.time() + 1800
        logger.debug("fetched NAIP SAS token, expires %s", expiry)
    return _token["value"]


def sign_url(href: str) -> str:
    """Append the SAS token so GDAL/requests can read the blob anonymously."""
    sep = "&" if "?" in href else "?"
    return f"{href}{sep}{_sas_token()}"


def search_naip(
    bbox: Sequence[float],
    year: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """NAIP STAC items covering a bbox, newest first.

    ``year`` pins a specific survey year; default returns all years
    (callers usually keep the newest tile per footprint).
    """
    body = {
        "collections": ["naip"],
        "bbox": list(bbox),
        "limit": min(limit, 250),
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }
    if year is not None:
        body["datetime"] = f"{year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z"
    resp = get_session().post(PC_STAC_URL, json=body, timeout=60)
    resp.raise_for_status()
    items = resp.json().get("features", [])
    logger.info("Planetary Computer: %d NAIP item(s) for %s", len(items), tuple(bbox))
    return items


def naip_tile_urls(
    bbox: Sequence[float], year: int | None = None
) -> list[str]:
    """Signed COG URLs covering a bbox — the newest acquisition per quad.

    NAIP quads are reflown every ~2 years; keeping only the newest per
    footprint avoids mixing years mid-mosaic where possible.
    """
    items = search_naip(bbox, year=year)
    if not items:
        raise TileNotFoundError(
            f"no NAIP tiles cover {tuple(bbox)} — NAIP is US-only; "
            "use load_sentinel2/composite (10 m, global) elsewhere"
        )
    newest: dict = {}
    for item in items:  # already newest-first
        quad = "_".join(item["id"].split("_")[1:4])  # e.g. m_3810928_sw
        newest.setdefault(quad, item)
    return [sign_url(it["assets"]["image"]["href"]) for it in newest.values()]


def load_naip(
    aoi,
    bands: Sequence[str] = ("R", "G", "B"),
    crs: str = "utm",
    res: float | None = None,
    year: int | None = None,
    clip: bool | None = None,
) -> xarray.DataArray:
    """US aerial imagery for any AOI as an ``xarray.DataArray``.

    Parameters
    ----------
    aoi : bbox, GeoJSON, .geojson path, shapely geometry, or place name.
    bands : subset of R, G, B, N (near-infrared).
    crs : output CRS; "utm" picks the AOI's zone.
    res : pixel size in CRS units; defaults to 1 m (native is 0.6-1 m).
    year : pin a survey year; default mosaics the newest available.
    clip : NaN-out pixels outside a polygon AOI. Defaults to True for
        polygons you pass explicitly, False for geocoded place names.

    Returns
    -------
    xarray.DataArray
        float32 (band, y, x) of 0-255 values, NaN nodata.
    """
    import numpy as np

    from .aoi import resolve_aoi, resolve_crs
    from .load import _resolve_res, _to_dataarray
    from .raster import make_grid, mask_to_geometry, warp_into_grid

    a = resolve_aoi(aoi)
    crs = resolve_crs(crs, a.bbox)
    urls = naip_tile_urls(a.bbox, year=year)
    res = _resolve_res(res, 1.0, crs)
    transform, width, height = make_grid(a.bbox, crs, res)
    logger.info("load_naip: %d tile(s) -> %dx%d @ %s", len(urls), width, height, crs)

    layers = [
        warp_into_grid(urls, transform, width, height, crs,
                       band=NAIP_BANDS[b.upper()])
        for b in bands
    ]
    data = np.stack(layers)
    if clip is None:
        clip = a.clip_default
    if clip and a.geometry is not None:
        mask_to_geometry(data, a.geometry, transform, crs)
    da = _to_dataarray(
        data, transform, width, height, crs, "naip",
        {"source": "naip", "year": year or "newest", "n_tiles": len(urls)},
    )
    return da.assign_coords(band=("band", [b.upper() for b in bands]))
