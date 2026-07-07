"""One-call array API: bbox in, aligned xarray out. Nothing hits disk.

Requires the ``xarray`` extra: ``pip install earthfetch[xarray]``.
Reads only the bbox window from remote COGs via HTTP range requests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray

from collections.abc import Sequence

import numpy as np

from .aoi import resolve_aoi, resolve_crs
from .copernicus import copernicus_dem_urls
from .exceptions import MissingDependencyError, TileNotFoundError
from .raster import make_grid, warp_into_grid
from .sentinel import (
    BAND_RESOLUTION,
    band_url,
    clearest_scene,
    resolve_bands,
    scale_offset,
)
from .usgs import dem_tile_urls
from .utils import logger

#: meters per degree at the equator, for geographic-CRS resolution defaults
_M_PER_DEG = 111_320.0

_DEM_NATIVE_M = {"1m": 1.0, "10m": 10.0, "30m": 30.0, "5m-ak": 5.0}


def _xr():
    try:
        import xarray as xr

        return xr
    except ImportError as exc:  # pragma: no cover
        raise MissingDependencyError(
            "xarray is required for load_* functions: pip install earthfetch[xarray]"
        ) from exc


def _is_geographic(crs: str) -> bool:
    from rasterio.crs import CRS

    return CRS.from_user_input(crs).is_geographic


def _resolve_res(res: float | None, native_m: float, crs: str) -> float:
    if res is not None:
        return float(res)
    return native_m / _M_PER_DEG if _is_geographic(crs) else native_m


def _coords(transform, width: int, height: int):
    xs = transform.c + transform.a * (np.arange(width) + 0.5)
    ys = transform.f + transform.e * (np.arange(height) + 0.5)
    return xs, ys


def _to_dataarray(data, transform, width, height, crs, name, attrs):
    xr = _xr()
    xs, ys = _coords(transform, width, height)
    dims = ("y", "x") if data.ndim == 2 else ("band", "y", "x")
    coords = {"y": ys, "x": xs}
    base_attrs = {"crs": str(crs), "transform": tuple(transform)[:6]}
    return xr.DataArray(data, dims=dims, coords=coords, name=name,
                        attrs={**base_attrs, **attrs})


def load_dem(
    bbox: Sequence[float],
    resolution: str = "10m",
    crs: str = "EPSG:4326",
    res: float | None = None,
    source: str = "auto",
) -> xarray.DataArray:
    """Load a DEM for a bbox as an ``xarray.DataArray`` — no files, no keys.

    Parameters
    ----------
    bbox : (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees.
    resolution : USGS dataset ("1m", "10m", "30m", "5m-ak"); ignored for
        the Copernicus source (always 30 m).
    crs : output CRS ("EPSG:32612", "EPSG:5070", ...).
    res : output pixel size in ``crs`` units; defaults to the native
        resolution (converted to degrees for geographic CRSs).
    source : "usgs", "copernicus", or "auto" (USGS first, Copernicus
        fallback outside the US).

    Returns
    -------
    xarray.DataArray
        float32 (y, x) elevation in meters, NaN nodata, with ``crs``,
        ``transform`` and ``sources`` attrs.
    """
    _xr()  # fail fast on missing xarray, before any network work
    a = resolve_aoi(bbox)
    bbox = a.bbox
    crs = resolve_crs(crs, bbox)
    urls: list = []
    used = source
    if source in ("usgs", "auto"):
        try:
            urls = dem_tile_urls(bbox, resolution=resolution)
            used = "usgs"
        except Exception:
            if source == "usgs":
                raise
    if not urls:
        if source == "usgs":
            raise TileNotFoundError(f"no USGS {resolution} tiles cover {bbox}")
        urls = copernicus_dem_urls(bbox)
        used = "copernicus"
        resolution = "30m"

    native = 30.0 if used == "copernicus" else _DEM_NATIVE_M[resolution]
    res = _resolve_res(res, native, crs)
    transform, width, height = make_grid(bbox, crs, res)
    logger.info("load_dem: %s %s -> %dx%d @ %s", used, resolution, width, height, crs)
    data = warp_into_grid(urls, transform, width, height, crs)
    return _to_dataarray(
        data, transform, width, height, crs, "dem",
        {"units": "m", "source": used, "resolution": resolution, "sources": urls},
    )


def load_sentinel2(
    bbox: Sequence[float],
    bands: Sequence[str] = ("B04", "B03", "B02"),
    crs: str = "EPSG:4326",
    res: float | None = None,
    item: dict | None = None,
    start: str | None = None,
    end: str | None = None,
    max_cloud: float = 20.0,
    scale: bool = True,
) -> xarray.DataArray:
    """Load Sentinel-2 L2A bands for a bbox as one aligned DataArray.

    Pass either a STAC ``item`` (from ``search_sentinel2``) or ``start``/
    ``end`` dates — then the clearest scene in the range is used.

    ``res`` defaults to the finest native resolution among ``bands``.
    ``scale=True`` (default) converts DNs to surface reflectance (0..1)
    using STAC metadata — matching ``composite``/``time_series`` so indices
    behave the same on every source; pass ``scale=False`` for raw DNs.
    Returns a float32 DataArray (band, y, x), NaN nodata, with scene
    metadata in attrs. Multi-band assets like TCI are not supported here —
    use ``download_sentinel2`` for those.
    """
    _xr()  # fail fast on missing xarray, before any network work
    a = resolve_aoi(bbox)
    bbox = a.bbox
    crs = resolve_crs(crs, bbox)
    bands = resolve_bands(bands)
    if item is None:
        if start is None or end is None:
            raise ValueError("pass item=... or start=/end= dates")
        item = clearest_scene(bbox, start, end, max_cloud=max_cloud)

    native = min(BAND_RESOLUTION.get(b.upper(), 10) for b in bands)
    res = _resolve_res(res, float(native), crs)
    transform, width, height = make_grid(bbox, crs, res)
    logger.info("load_sentinel2: %s %s -> %dx%d @ %s",
                item["id"], list(bands), width, height, crs)

    layers = []
    for b in bands:
        layer = warp_into_grid([band_url(item, b)], transform, width, height, crs)
        if scale:
            sc, off = scale_offset(item, b)
            layer = np.where(np.isfinite(layer),
                             np.maximum(layer * sc + off, 0.0), np.nan)
        layers.append(layer)
    data = np.stack(layers)
    da = _to_dataarray(
        data, transform, width, height, crs, "sentinel2",
        {
            "scene_id": item["id"],
            "datetime": item["properties"].get("datetime"),
            "cloud_cover": item["properties"].get("eo:cloud_cover"),
            "reflectance": scale,
            "sources": [band_url(item, b) for b in bands],
        },
    )
    return da.assign_coords(band=("band", [b.upper() for b in bands]))


def stack(
    bbox: Sequence[float],
    crs: str,
    res: float,
    bands: Sequence[str] = ("B04", "B08"),
    start: str | None = None,
    end: str | None = None,
    max_cloud: float = 20.0,
    item: dict | None = None,
    dem_resolution: str = "10m",
    dem_source: str = "auto",
    scale: bool = True,
) -> xarray.Dataset:
    """DEM + Sentinel-2 bands on one pixel-aligned grid — ML-ready.

    Sentinel-2 bands are surface reflectance (0..1) by default, matching the
    rest of the array API; pass ``scale=False`` for raw DNs. Returns an
    ``xarray.Dataset`` with a ``dem`` variable plus one variable per band
    (``B04``, ``B08``, ...), all float32 on the same (y, x) grid.
    """
    xr = _xr()
    a = resolve_aoi(bbox)
    bbox = a.bbox
    crs = resolve_crs(crs, bbox)
    dem = load_dem(bbox, resolution=dem_resolution, crs=crs, res=res,
                   source=dem_source)
    s2 = load_sentinel2(bbox, bands=bands, crs=crs, res=res, item=item,
                        start=start, end=end, max_cloud=max_cloud, scale=scale)
    ds = xr.Dataset({"dem": dem})
    for b in s2.band.values:
        ds[str(b)] = s2.sel(band=b).drop_vars("band")
    ds.attrs = {**s2.attrs, "dem_source": dem.attrs["source"], "crs": str(crs)}
    return ds


def elevation(points, source: str = "auto", resolution: str = "10m"):
    """Elevation in meters at one or more ``(lon, lat)`` points.

    The most direct question a DEM answers. Loads a DEM covering the points
    (USGS in the US, Copernicus elsewhere) and samples it.

    Parameters
    ----------
    points : a single ``(lon, lat)``, a list of them, or GeoJSON
        Point/MultiPoint (WGS84).
    source : "usgs", "copernicus", or "auto".
    resolution : DEM resolution when the USGS source is used.

    Returns
    -------
    float or numpy.ndarray
        A float for a single point, else an array of elevations (NaN where
        outside coverage). Best for nearby points — far-apart points load a
        DEM spanning their whole bounding box.
    """
    from .zonal import _as_points, sample

    pts = _as_points(points)
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    pad = 0.002
    bbox = (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)
    dem = load_dem(bbox, resolution=resolution, crs="utm", source=source)
    vals = sample(dem, pts)
    return float(vals[0]) if len(pts) == 1 else vals
