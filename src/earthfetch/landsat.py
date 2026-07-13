"""Landsat Collection-2 Level-2 surface reflectance (Landsat 8/9) via the
Microsoft Planetary Computer — no API key required.

Uses the ``landsat-c2-l2`` collection (free, SAS-signed like NAIP), so it
stays zero-key (the AWS Landsat bucket is requester-pays). Band labels on the
returned array are normalized to their **Sentinel-2-equivalent ids**
(red→``B04``, nir→``B08``, ...), so ``ef.ndvi`` and the other indices work on
Landsat exactly as they do on Sentinel-2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray

from collections.abc import Sequence

from .exceptions import BandNotFoundError, NoScenesError
from .utils import get_session, logger, validate_bbox

PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
COLLECTION = "landsat-c2-l2"

#: any accepted band spelling -> (STAC asset key, Sentinel-2-equivalent label)
_BANDS = {
    "coastal": ("coastal", "B01"), "b1": ("coastal", "B01"),
    "blue": ("blue", "B02"), "b2": ("blue", "B02"), "b02": ("blue", "B02"),
    "green": ("green", "B03"), "b3": ("green", "B03"), "b03": ("green", "B03"),
    "red": ("red", "B04"), "b4": ("red", "B04"), "b04": ("red", "B04"),
    "nir": ("nir08", "B08"), "nir08": ("nir08", "B08"),
    "b5": ("nir08", "B08"), "b08": ("nir08", "B08"), "b8a": ("nir08", "B08"),
    "swir1": ("swir16", "B11"), "swir16": ("swir16", "B11"),
    "b6": ("swir16", "B11"), "b11": ("swir16", "B11"),
    "swir2": ("swir22", "B12"), "swir22": ("swir22", "B12"),
    "b7": ("swir22", "B12"), "b12": ("swir22", "B12"),
    "thermal": ("lwir11", "B10"), "lwir11": ("lwir11", "B10"),
    "b10": ("lwir11", "B10"),
    "qa": ("qa_pixel", "QA"), "qa_pixel": ("qa_pixel", "QA"),
}

#: Landsat C2 L2 surface-reflectance DN scaling (fallback if not in metadata)
_SR_SCALE, _SR_OFFSET = 2.75e-5, -0.2

#: QA_PIXEL bits that mark an unusable pixel: fill, dilated cloud, cirrus,
#: cloud, cloud shadow
_QA_BAD = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)


def _resolve_band(band: str):
    key = str(band).lower()
    if key not in _BANDS:
        raise BandNotFoundError(
            f"unknown Landsat band {band!r}; use red/green/blue/nir/swir1/"
            "swir2/coastal/thermal, a Landsat id (B4), or a Sentinel id (B04)"
        )
    return _BANDS[key]


def sign_mpc(href: str) -> str:
    """Sign a Planetary Computer asset href (anonymous SAS)."""
    resp = get_session().get(PC_SIGN_URL, params={"href": href}, timeout=30)
    resp.raise_for_status()
    return resp.json()["href"]


def band_url(item: dict, band: str) -> str:
    """Signed COG URL for one Landsat band of a STAC item."""
    asset_key, _ = _resolve_band(band)
    assets = item["assets"]
    if asset_key not in assets:
        raise BandNotFoundError(
            f"asset {asset_key!r} not in scene {item.get('id')}; "
            f"available: {sorted(assets)}"
        )
    return sign_mpc(assets[asset_key]["href"])


def scale_offset(item: dict, band: str) -> tuple:
    """(scale, offset) to surface reflectance for a Landsat band."""
    asset_key, _ = _resolve_band(band)
    if asset_key in ("qa_pixel", "lwir11"):
        return (1.0, 0.0)
    rb = (item["assets"].get(asset_key, {}).get("raster:bands") or [{}])[0]
    return (rb.get("scale", _SR_SCALE), rb.get("offset", _SR_OFFSET))


def search_landsat(
    bbox: Sequence[float], start: str, end: str,
    max_cloud: float = 20.0, limit: int = 50,
) -> list[dict]:
    """Search Landsat 8/9 Collection-2 L2 scenes, clearest first."""
    bbox = validate_bbox(bbox)
    body = {
        "collections": [COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": min(limit, 100),
        "query": {"eo:cloud_cover": {"lt": max_cloud},
                  "platform": {"in": ["landsat-8", "landsat-9"]}},
    }
    resp = get_session().post(PC_STAC_URL, json=body, timeout=60)
    resp.raise_for_status()
    items = resp.json().get("features", [])
    items.sort(key=lambda i: i["properties"].get("eo:cloud_cover", 100))
    logger.info("Planetary Computer: %d Landsat scene(s) %s..%s", len(items),
                start, end)
    return items[:limit]


def clearest_landsat(bbox, start, end, max_cloud=20.0) -> dict:
    """Least-cloudy Landsat scene in a date range, or ``NoScenesError``."""
    items = search_landsat(bbox, start, end, max_cloud=max_cloud)
    if not items:
        raise NoScenesError(
            f"no Landsat scenes for {tuple(bbox)} in {start}..{end} "
            f"with cloud < {max_cloud}%")
    return items[0]


def load_landsat(
    bbox: Sequence[float],
    bands: Sequence[str] = ("red", "green", "blue"),
    crs: str = "EPSG:4326",
    res: float | None = None,
    item: dict | None = None,
    items: Sequence[dict] | None = None,
    start: str | None = None,
    end: str | None = None,
    max_cloud: float = 20.0,
    scale: bool = True,
) -> xarray.DataArray:
    """Load Landsat 8/9 bands for a bbox as one aligned DataArray.

    Accepts a single ``item``, a list of ``items``, or ``start``/``end`` dates
    (the clearest scene is used). Bands may be common names (``red``, ``nir``,
    ``swir1``), Landsat ids (``B4``), Sentinel ids (``B04``), or a preset
    (``"true_color"``). Output band labels are the Sentinel-2 equivalents so
    indices work unchanged. ``scale=True`` returns surface reflectance (0..1).
    """
    from .aoi import resolve_aoi, resolve_crs
    from .sentinel import resolve_bands

    try:
        import numpy as np

        from .load import _resolve_res, _to_dataarray, _xr
        from .raster import make_grid, warp_into_grid

        _xr()
    except ImportError as exc:
        from .exceptions import MissingDependencyError

        raise MissingDependencyError(
            "'load_landsat' needs the optional 'xarray' dependencies; "
            "install with: pip install 'earthfetch[xarray]'"
        ) from exc

    a = resolve_aoi(bbox)
    bbox = a.bbox
    crs = resolve_crs(crs, bbox)
    bands = resolve_bands(bands)
    if items is None:
        items = [item] if item is not None else [
            clearest_landsat(bbox, start, end, max_cloud=max_cloud)]
    items = list(items)

    res = _resolve_res(res, 30.0, crs)   # Landsat is 30 m
    transform, width, height = make_grid(bbox, crs, res)
    logger.info("load_landsat: %d scene(s) %s -> %dx%d @ %s",
                len(items), list(bands), width, height, crs)

    layers, labels = [], []
    for b in bands:
        layer = warp_into_grid([band_url(it, b) for it in items],
                               transform, width, height, crs)
        if scale:
            sc, off = scale_offset(items[0], b)
            layer = np.where(np.isfinite(layer),
                             np.maximum(layer * sc + off, 0.0), np.nan)
        layers.append(layer)
        labels.append(_resolve_band(b)[1])
    data = np.stack(layers)
    da = _to_dataarray(
        data, transform, width, height, crs, "landsat",
        {"scene_ids": [it["id"] for it in items],
         "datetime": items[0]["properties"].get("datetime"),
         "cloud_cover": items[0]["properties"].get("eo:cloud_cover"),
         "reflectance": scale, "source": "landsat"},
    )
    return da.assign_coords(band=("band", labels))
