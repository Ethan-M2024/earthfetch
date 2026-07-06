"""Cloud-masked multi-scene composites — the one-liner that replaces an
afternoon of manual downloading, masking, and mosaicking.

Requires the ``xarray`` extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray

from collections import defaultdict
from collections.abc import Sequence

import numpy as np

from .aoi import resolve_aoi, resolve_crs
from .exceptions import NoScenesError
from .raster import Resampling, make_grid, mask_to_geometry, warp_into_grid
from .sentinel import (
    BAND_RESOLUTION,
    band_url,
    scale_offset,
    search_sentinel2,
)
from .utils import logger

#: SCL classes masked as invalid: nodata, saturated, cloud shadow,
#: cloud medium/high probability, thin cirrus
SCL_INVALID = (0, 1, 3, 8, 9, 10)


def _xr():
    from .load import _xr as inner

    return inner()


def _select_day_groups(items: Sequence[dict], max_scenes: int) -> list:
    """Group scenes by acquisition day (one satellite pass covers the whole
    bbox across MGRS tile boundaries), rank days by mean cloud cover, and
    keep the clearest ``max_scenes`` days.
    """
    days = defaultdict(list)
    for it in items:
        days[it["properties"]["datetime"][:10]].append(it)
    ranked = sorted(
        days.values(),
        key=lambda g: sum(i["properties"].get("eo:cloud_cover", 100) for i in g)
        / len(g),
    )
    return ranked[:max_scenes]


def composite(
    aoi,
    bands: Sequence[str] = ("B04", "B03", "B02"),
    start: str = None,
    end: str = None,
    crs: str = "utm",
    res: float | None = None,
    method: str = "median",
    mask_clouds: bool = True,
    max_cloud: float = 60.0,
    max_scenes: int = 8,
    scale: bool = True,
    clip: bool = None,
) -> xarray.DataArray:
    """Cloud-free composite of Sentinel-2 bands over a date range.

    Searches every scene touching the AOI, keeps the ``max_scenes`` clearest
    acquisition days (all MGRS tiles of each day, so seams disappear), masks
    invalid pixels with the SCL layer, and reduces per pixel.

    Parameters
    ----------
    aoi : bbox tuple, GeoJSON, .geojson path, shapely geometry, or place name.
    bands : ESA band ids. SCL/TCI are not composable inputs here.
    start, end : ISO dates bounding the search.
    crs : output CRS; "utm" (default) picks the AOI's UTM zone.
    res : pixel size in CRS units; defaults to the finest native band res.
    method : "median" (robust, default), "mean", or "first" (first valid,
        clearest day first — fastest).
    mask_clouds : mask SCL classes {0,1,3,8,9,10} before compositing.
    max_cloud : scene-level cloud prefilter for the search.
    max_scenes : acquisition days to blend.
    scale : convert DNs to surface reflectance (0..1) using STAC metadata.
    clip : NaN-out pixels outside a polygon AOI. Default (None): clip
        polygons you passed explicitly, but keep the full rectangle for
        geocoded place names (pass clip=True to cut to a city boundary).

    Returns
    -------
    xarray.DataArray
        float32 (band, y, x), NaN nodata, with the scene ids and dates
        used in ``attrs``.
    """
    if method not in ("median", "mean", "first"):
        raise ValueError("method must be 'median', 'mean', or 'first'")
    a = resolve_aoi(aoi)
    crs = resolve_crs(crs, a.bbox)
    items = search_sentinel2(a.bbox, start, end, max_cloud=max_cloud, limit=100)
    if not items:
        raise NoScenesError(
            f"no scenes for {a.bbox} in {start}..{end} with cloud < {max_cloud}%"
        )
    groups = _select_day_groups(items, max_scenes)
    scenes = [it for g in groups for it in g]
    logger.info("composite: %d scene(s) over %d day(s), method=%s",
                len(scenes), len(groups), method)

    native = min(BAND_RESOLUTION.get(b.upper(), 10) for b in bands)
    from .load import _resolve_res, _to_dataarray

    res = _resolve_res(res, float(native), crs)
    transform, width, height = make_grid(a.bbox, crs, res)

    acc = np.full((len(bands), height, width), np.nan, dtype="float32")
    stacks: list = []
    for item in scenes:
        valid = None
        if mask_clouds:
            scl = warp_into_grid([band_url(item, "SCL")], transform, width,
                                 height, crs, resampling=Resampling.nearest)
            valid = np.isfinite(scl) & ~np.isin(scl, SCL_INVALID)
        layer = np.full((len(bands), height, width), np.nan, dtype="float32")
        for i, b in enumerate(bands):
            data = warp_into_grid([band_url(item, b)], transform, width,
                                  height, crs)
            if scale:
                sc, off = scale_offset(item, b)
                data = np.where(np.isfinite(data),
                                np.maximum(data * sc + off, 0.0), np.nan)
            if valid is not None:
                data = np.where(valid, data, np.nan)
            layer[i] = data
        if method == "first":
            hole = np.isnan(acc)
            acc[hole] = layer[hole]
            if not np.isnan(acc).any():
                break
        else:
            stacks.append(layer)

    if method == "median" and stacks:
        acc = np.nanmedian(np.stack(stacks), axis=0)
    elif method == "mean" and stacks:
        acc = np.nanmean(np.stack(stacks), axis=0)

    if clip is None:
        clip = a.clip_default
    if clip and a.geometry is not None:
        mask_to_geometry(acc, a.geometry, transform, crs)

    da = _to_dataarray(
        acc.astype("float32"), transform, width, height, crs, "composite",
        {
            "method": method,
            "scenes": [it["id"] for it in scenes],
            "dates": sorted({it["properties"]["datetime"][:10] for it in scenes}),
            "cloud_masked": mask_clouds,
            "reflectance": scale,
            "aoi_name": a.name or "",
        },
    )
    return da.assign_coords(band=("band", [b.upper() for b in bands]))
