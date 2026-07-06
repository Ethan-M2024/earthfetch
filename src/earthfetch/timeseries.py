"""Sentinel-2 time-series datacubes: bbox in, ``(time, band, y, x)`` out.

Where ``composite`` collapses a date range to one cloud-free image, this
keeps every clear acquisition as its own time step — the datacube analysts
use for change detection, phenology, and trend analysis.

Requires the ``xarray`` extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray

from collections.abc import Sequence

import numpy as np

from ._composite import SCL_INVALID, _select_day_groups
from .aoi import resolve_aoi, resolve_crs
from .exceptions import NoScenesError
from .raster import Resampling, make_grid, mask_to_geometry, warp_into_grid
from .sentinel import (
    BAND_RESOLUTION,
    band_url,
    resolve_bands,
    scale_offset,
    search_sentinel2,
)
from .utils import logger


def _render_scene(item, bands, transform, width, height, crs, mask_clouds, scale):
    """One scene warped to the grid: (band, y, x), NaN where cloudy/invalid."""
    valid = None
    if mask_clouds:
        scl = warp_into_grid([band_url(item, "SCL")], transform, width, height,
                             crs, resampling=Resampling.nearest)
        valid = np.isfinite(scl) & ~np.isin(scl, SCL_INVALID)
    out = np.full((len(bands), height, width), np.nan, dtype="float32")
    for i, b in enumerate(bands):
        data = warp_into_grid([band_url(item, b)], transform, width, height, crs)
        if scale:
            sc, off = scale_offset(item, b)
            data = np.where(np.isfinite(data),
                            np.maximum(data * sc + off, 0.0), np.nan)
        if valid is not None:
            data = np.where(valid, data, np.nan)
        out[i] = data
    return out


def time_series(
    aoi,
    bands: Sequence[str] = ("B04", "B03", "B02"),
    start: str = None,
    end: str = None,
    crs: str = "utm",
    res: float | None = None,
    max_cloud: float = 60.0,
    mask_clouds: bool = True,
    scale: bool = True,
    max_steps: int = 50,
    freq: str | None = None,
    clip: bool = None,
) -> xarray.DataArray:
    """Cloud-masked Sentinel-2 time series over a date range.

    Each clear acquisition day becomes a time step; the day's MGRS tiles are
    mosaicked together (first valid pixel wins), cloud/shadow pixels are
    masked with SCL, and values are reflectance-scaled.

    Parameters
    ----------
    aoi : bbox tuple, GeoJSON, .geojson path, shapely geometry, or place name.
    bands : ESA band ids. SCL/TCI are not composable inputs here.
    start, end : ISO dates bounding the search.
    crs : output CRS; "utm" (default) picks the AOI's UTM zone.
    res : pixel size in CRS units; defaults to the finest native band res.
    max_cloud : scene-level cloud prefilter for the search.
    mask_clouds : mask SCL classes {0,1,3,8,9,10} before stacking.
    scale : convert DNs to surface reflectance (0..1) using STAC metadata.
    max_steps : cap on acquisition days (time steps) returned.
    freq : optional pandas offset alias ("MS", "W", "QS", ...) to resample
        the time axis with a per-period median (e.g. monthly composites).
    clip : NaN-out pixels outside a polygon AOI (see ``composite``).

    Returns
    -------
    xarray.DataArray
        float32 (time, band, y, x), NaN nodata, ``time`` as datetime64 and
        ``band`` as ESA ids, with ``crs``/``transform`` in ``attrs``.
    """
    from .load import _coords, _resolve_res, _xr

    xr = _xr()
    bands = resolve_bands(bands)
    a = resolve_aoi(aoi)
    crs = resolve_crs(crs, a.bbox)
    items = search_sentinel2(a.bbox, start, end, max_cloud=max_cloud, limit=100)
    if not items:
        raise NoScenesError(
            f"no scenes for {a.bbox} in {start}..{end} with cloud < {max_cloud}%"
        )
    groups = _select_day_groups(items, max_steps)
    groups.sort(key=lambda g: g[0]["properties"]["datetime"][:10])  # time order
    logger.info("time_series: %d day(s), bands=%s", len(groups), list(bands))

    native = min(BAND_RESOLUTION.get(b.upper(), 10) for b in bands)
    res = _resolve_res(res, float(native), crs)
    transform, width, height = make_grid(a.bbox, crs, res)
    do_clip = a.clip_default if clip is None else clip

    times, slices = [], []
    for g in groups:
        day = g[0]["properties"]["datetime"][:10]
        layer = np.full((len(bands), height, width), np.nan, dtype="float32")
        for scene in g:  # fill holes across the day's tiles
            s = _render_scene(scene, bands, transform, width, height, crs,
                              mask_clouds, scale)
            hole = np.isnan(layer)
            layer[hole] = s[hole]
        if do_clip and a.geometry is not None:
            mask_to_geometry(layer, a.geometry, transform, crs)
        times.append(np.datetime64(day))
        slices.append(layer)

    xs, ys = _coords(transform, width, height)
    da = xr.DataArray(
        np.stack(slices),
        dims=("time", "band", "y", "x"),
        coords={"time": times, "band": [b.upper() for b in bands],
                "y": ys, "x": xs},
        name="sentinel2",
        attrs={
            "crs": str(crs),
            "transform": tuple(transform)[:6],
            "reflectance": scale,
            "cloud_masked": mask_clouds,
            "aoi_name": a.name or "",
        },
    )
    if freq:
        da = da.resample(time=freq).median()
        da.attrs.update({"crs": str(crs), "transform": tuple(transform)[:6]})
    return da
