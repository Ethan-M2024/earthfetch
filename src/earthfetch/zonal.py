"""Extract values from earthfetch rasters at points and over polygons.

``sample`` reads pixel values at coordinates (elevation at stations, band
values at plots); ``zonal_stats`` aggregates over polygons (mean NDVI per
field, elevation stats per watershed). Both take any earthfetch DataArray
or Dataset and any AOI-style vector input.

Requires the ``raster`` extra (rasterio).
"""

from __future__ import annotations

import numpy as np

from .exceptions import EarthfetchError

try:
    from rasterio.transform import Affine, rowcol
    from rasterio.warp import transform as _warp_xy
except ImportError as exc:  # pragma: no cover
    from .exceptions import MissingDependencyError

    raise MissingDependencyError(
        "rasterio is required for sampling/zonal stats: "
        "pip install earthfetch[raster]"
    ) from exc

_STATS = {
    "mean": np.nanmean,
    "min": np.nanmin,
    "max": np.nanmax,
    "std": np.nanstd,
    "median": np.nanmedian,
    "sum": np.nansum,
}


def _georef(obj):
    attrs = getattr(obj, "attrs", {})
    if "transform" not in attrs or "crs" not in attrs:
        raise EarthfetchError(
            "object lacks crs/transform attrs; pass an earthfetch result"
        )
    return Affine(*attrs["transform"]), attrs["crs"]


def _as_points(points) -> list[tuple[float, float]]:
    """Normalize point input to a list of (lon, lat) in WGS84."""
    if hasattr(points, "__geo_interface__"):
        points = dict(points.__geo_interface__)
    if isinstance(points, dict):
        t = points.get("type")
        if t == "FeatureCollection":
            return [p for f in points["features"]
                    for p in _as_points(f["geometry"])]
        if t == "Feature":
            return _as_points(points["geometry"])
        if t == "Point":
            return [tuple(points["coordinates"][:2])]
        if t == "MultiPoint":
            return [tuple(c[:2]) for c in points["coordinates"]]
        raise EarthfetchError(f"not a point geometry: {t!r}")
    seq = list(points)
    if len(seq) == 2 and all(isinstance(v, (int, float)) for v in seq):
        return [(float(seq[0]), float(seq[1]))]  # a single (lon, lat)
    return [(float(x), float(y)) for x, y in seq]


def _as_geometries(polygons) -> list[dict]:
    """Normalize polygon input to a list of WGS84 GeoJSON geometry dicts."""
    if hasattr(polygons, "__geo_interface__"):
        polygons = dict(polygons.__geo_interface__)
    if isinstance(polygons, dict):
        t = polygons.get("type")
        if t == "FeatureCollection":
            return [f["geometry"] for f in polygons["features"]]
        if t == "Feature":
            return [polygons["geometry"]]
        if t in ("Polygon", "MultiPolygon"):
            return [polygons]
        raise EarthfetchError(f"not a polygon geometry: {t!r}")
    return [g for p in polygons for g in _as_geometries(p)]


def _band_names(obj, n: int) -> list[str]:
    if "band" in getattr(obj, "coords", {}):
        return [str(b) for b in np.atleast_1d(obj.band.values)]
    return [obj.name or f"band{i + 1}" for i in range(n)]


def sample(obj, points):
    """Read raster values at points (nearest pixel).

    Parameters
    ----------
    obj : an earthfetch DataArray (2D ``(y, x)`` or 3D ``(band, y, x)``).
    points : a single ``(lon, lat)``, a list of them, or GeoJSON
        Point/MultiPoint/Feature/FeatureCollection (WGS84).

    Returns
    -------
    numpy.ndarray
        Shape ``(n_points,)`` for a 2D input, or ``(n_bands, n_points)``
        for a banded input. Points outside the raster are NaN.
    """
    transform, crs = _georef(obj)
    pts = _as_points(points)
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    xs, ys = _warp_xy("EPSG:4326", crs, lons, lats)
    rows, cols = rowcol(transform, xs, ys)
    rows = np.atleast_1d(np.asarray(rows, dtype=int))
    cols = np.atleast_1d(np.asarray(cols, dtype=int))
    data = np.asarray(obj.values, dtype="float32")
    h, w = data.shape[-2], data.shape[-1]
    inb = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)

    if data.ndim == 2:
        out = np.full(len(rows), np.nan, dtype="float32")
        out[inb] = data[rows[inb], cols[inb]]
        return out
    out = np.full((data.shape[0], len(rows)), np.nan, dtype="float32")
    out[:, inb] = data[:, rows[inb], cols[inb]]
    return out


def zonal_stats(obj, polygons, stats=("mean", "min", "max", "std", "count")):
    """Aggregate raster values within each polygon.

    Parameters
    ----------
    obj : an earthfetch DataArray (2D or banded 3D).
    polygons : GeoJSON Polygon/MultiPolygon/Feature/FeatureCollection, a
        shapely geometry, or a list of any of these (WGS84).
    stats : any of "mean", "min", "max", "std", "median", "sum", plus
        "count" (number of valid pixels).

    Returns
    -------
    list of dict
        One dict per polygon. For a 2D input each dict maps stat name to
        value; for a banded input it maps ``band -> {stat: value}``.
    """
    from .raster import mask_to_geometry

    transform, crs = _georef(obj)
    geoms = _as_geometries(polygons)
    data = np.asarray(obj.values, dtype="float32")
    banded = data.ndim == 3
    names = _band_names(obj, data.shape[0]) if banded else None

    results = []
    for geom in geoms:
        masked = mask_to_geometry(data.copy(), geom, transform, crs)
        if banded:
            results.append({names[i]: _reduce(masked[i], stats)
                            for i in range(masked.shape[0])})
        else:
            results.append(_reduce(masked, stats))
    return results


def _reduce(arr: np.ndarray, stats) -> dict:
    valid = arr[np.isfinite(arr)]
    out = {}
    for s in stats:
        if s == "count":
            out["count"] = int(valid.size)
        elif s in _STATS:
            out[s] = float(_STATS[s](valid)) if valid.size else float("nan")
        else:
            raise EarthfetchError(f"unknown stat {s!r}; pick from "
                                  f"{sorted(_STATS) + ['count']}")
    return out
