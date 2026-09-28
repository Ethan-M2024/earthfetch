"""Relative Elevation Models: terrain height above the nearby river.

A REM subtracts a water-surface estimate from the DEM, flattening the valley
so the river sits at zero and every terrace, abandoned channel, and flood-prone
swale shows up as height above the channel. The water surface comes from
sampling the DEM along the river centerline and spreading those values across
the valley with inverse-distance weighting (the standard approach, after
Olson et al. 2014, Washington Geological Survey).

Requires the ``xarray`` extra. SciPy is used for the nearest-neighbour search
when installed, and a chunked NumPy search otherwise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray

import os
from pathlib import Path

import numpy as np

from .aoi import resolve_aoi, resolve_crs
from .exceptions import EarthfetchError
from .utils import logger

#: coarse base-surface cells; the surface is smooth, so it is interpolated
#: on a grid this size and resampled to full resolution
_BASE_CELLS = 250_000
#: at most this many river samples feed the interpolation
_MAX_POINTS = 5_000


def _river_geometry(river, aoi) -> tuple[dict, str | None, str]:
    """(WGS84 line geometry, river name, source) from rem()'s ``river`` arg."""
    from .rivers import river_centerline

    if river is None:
        feat = river_centerline(aoi)
    elif isinstance(river, (str, os.PathLike)) and not Path(str(river)).is_file():
        feat = river_centerline(aoi, name=str(river))
    else:
        if isinstance(river, (str, os.PathLike)):
            from .aoi import resolve_aoi as _resolve

            geom = _resolve(river).geometry
        elif hasattr(river, "__geo_interface__"):
            geom = dict(river.__geo_interface__)
        else:
            geom = river
        if geom and geom.get("type") == "Feature":
            geom = geom["geometry"]
        if geom and geom.get("type") == "FeatureCollection":
            geom = {"type": "MultiLineString", "coordinates": [
                c for f in geom["features"] for c in _parts(f["geometry"])]}
        if not geom or not _parts(geom):
            raise EarthfetchError("river must be a LineString/MultiLineString, "
                                  "a vector file of lines, or a river name")
        feat = {"geometry": geom, "properties": {"name": None, "source": "user"}}
    props = feat.get("properties", {})
    return feat["geometry"], props.get("name"), props.get("source", "user")


def _parts(geom: dict) -> list:
    t = geom.get("type")
    if t == "LineString":
        return [geom["coordinates"]]
    if t == "MultiLineString":
        return list(geom["coordinates"])
    if t == "GeometryCollection":
        return [c for g in geom["geometries"] for c in _parts(g)]
    return []


def _densify(line: np.ndarray, spacing: float) -> np.ndarray:
    """Points every ``spacing`` units along a projected polyline."""
    seg = np.hypot(*np.diff(line, axis=0).T)
    dist = np.concatenate([[0.0], np.cumsum(seg)])
    if dist[-1] <= 0:
        return line[:1]
    at = np.arange(0.0, dist[-1] + 1e-9, spacing)
    return np.column_stack([np.interp(at, dist, line[:, 0]),
                            np.interp(at, dist, line[:, 1])])


def _rolling_median(z: np.ndarray, window: int) -> np.ndarray:
    """Centered running median; knocks out bridge decks and DEM spikes."""
    if window < 3 or z.size < window:
        return z
    half = window // 2
    padded = np.pad(z, half, mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.nanmedian(view, axis=1)


def _sample_profile(dem: np.ndarray, transform, pts: np.ndarray,
                    radius_px: int) -> np.ndarray:
    """Water-surface elevation at each point: a low percentile of the DEM in
    a small window, so a centerline a few pixels off the channel (common with
    mapped hydrography) still lands on the water, not the bank."""
    inv = ~transform
    cols, rows = inv * (pts[:, 0], pts[:, 1])
    rows = np.floor(rows).astype(int)
    cols = np.floor(cols).astype(int)
    h, w = dem.shape
    out = np.full(len(pts), np.nan, dtype="float64")
    r = radius_px
    for i, (row, col) in enumerate(zip(rows, cols)):
        if not (0 <= row < h and 0 <= col < w):
            continue
        win = dem[max(0, row - r):row + r + 1, max(0, col - r):col + r + 1]
        vals = win[np.isfinite(win)]
        if vals.size:
            out[i] = np.percentile(vals, 10)
    return out


def _idw(xy: np.ndarray, z: np.ndarray, qx: np.ndarray, qy: np.ndarray,
         k: int, power: float) -> np.ndarray:
    """Inverse-distance-weighted values of (xy, z) at query points."""
    q = np.column_stack([qx.ravel(), qy.ravel()])
    k = min(k, len(z))
    try:
        from scipy.spatial import cKDTree

        dist, idx = cKDTree(xy).query(q, k=k)
        if k == 1:
            dist, idx = dist[:, None], idx[:, None]
    except ImportError:
        dist = np.empty((len(q), k))
        idx = np.empty((len(q), k), dtype=int)
        step = max(1, 20_000_000 // max(1, len(xy)))
        for s in range(0, len(q), step):
            d = np.hypot(q[s:s + step, 0, None] - xy[None, :, 0],
                         q[s:s + step, 1, None] - xy[None, :, 1])
            part = np.argpartition(d, k - 1, axis=1)[:, :k]
            idx[s:s + step] = part
            dist[s:s + step] = np.take_along_axis(d, part, axis=1)
    wts = 1.0 / np.maximum(dist, 1e-6) ** power
    vals = (wts * z[idx]).sum(axis=1) / wts.sum(axis=1)
    return vals.reshape(qx.shape)


def rem(
    aoi,
    river=None,
    resolution: str = "10m",
    crs: str = "utm",
    res: float | None = None,
    source: str = "auto",
    spacing: float | None = None,
    k: int = 48,
    power: float = 2.0,
    clip: bool | None = None,
) -> xarray.Dataset:
    """Relative Elevation Model for any AOI in one call.

    Downloads the DEM, finds the river (USGS NHD in the US, OpenStreetMap
    worldwide), samples its water surface, interpolates that surface across
    the valley, and subtracts it — the whole floodplain-mapping workflow.

    Parameters
    ----------
    aoi : bbox, GeoJSON, vector file path, shapely geometry, or place name.
        Draw it around a valley segment; a few km of river is ideal.
    river : which river to measure from. ``None`` picks the main named river
        in the AOI; a string picks a river by name ("Snake"); a GeoJSON
        line, shapely line, or vector file supplies your own centerline.
    resolution, source : DEM choice, as in ``load_dem``. "1m" lidar gives
        the most striking maps where 3DEP has it.
    crs, res : output grid (defaults: the AOI's UTM zone, native DEM pixel).
    spacing : distance between river samples in CRS units (default: 3
        pixels).
    k, power : inverse-distance weighting neighbours and exponent.
    clip : NaN-out pixels outside a polygon AOI.

    Returns
    -------
    xarray.Dataset
        ``rem`` (meters above the river), ``dem`` (meters), ``water_surface``
        (the interpolated river surface), and ``hillshade`` (0-255), all
        float32 on one grid. Attrs record the river name and centerline
        source. For the classic map:
        ``ef.preview(r.rem, "rem.png", cmap="YlGnBu_r", vmin=0, vmax=6,
        shade=r.hillshade)``.
    """
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject, transform_geom

    from .load import _xr, load_dem
    from .raster import mask_to_geometry

    xr = _xr()
    a = resolve_aoi(aoi)
    crs = resolve_crs(crs, a.bbox)
    geom, river_name, river_source = _river_geometry(river, a)
    dem = load_dem(a.bbox, resolution=resolution, crs=crs, res=res, source=source)
    z = dem.values.astype("float32")
    transform = Affine(*dem.attrs["transform"])
    pixel = abs(transform.a)
    spacing = float(spacing) if spacing else 3 * pixel

    projected = transform_geom("EPSG:4326", crs, geom)
    pts_list, prof_list = [], []
    for part in _parts(projected):
        line = np.asarray(part, dtype="float64")[:, :2]
        if len(line) < 2:
            continue
        pts = _densify(line, spacing)
        prof = _sample_profile(z, transform, pts, radius_px=2)
        keep = np.isfinite(prof)
        if keep.sum() < 2:
            continue
        pts, prof = pts[keep], prof[keep]
        prof = _rolling_median(prof, window=7)
        pts_list.append(pts)
        prof_list.append(prof)
    if not pts_list:
        raise EarthfetchError(
            f"the river{f' {river_name!r}' if river_name else ''} does not "
            "cross the DEM; widen the AOI or pass river=<line>"
        )
    xy = np.concatenate(pts_list)
    zs = np.concatenate(prof_list)
    if len(zs) > _MAX_POINTS:
        pick = np.linspace(0, len(zs) - 1, _MAX_POINTS).astype(int)
        xy, zs = xy[pick], zs[pick]
    logger.info("rem: %s (%s), %d river samples every %.0f units",
                river_name or "river", river_source, len(zs), spacing)

    h, w = z.shape
    factor = max(1, int(np.ceil(np.sqrt(h * w / _BASE_CELLS))))
    ch, cw = int(np.ceil(h / factor)), int(np.ceil(w / factor))
    coarse_tf = transform * Affine.scale(factor)
    cols, rows = np.meshgrid(np.arange(cw) + 0.5, np.arange(ch) + 0.5)
    qx, qy = coarse_tf * (cols, rows)
    coarse = _idw(xy, zs, qx, qy, k=k, power=power).astype("float32")

    base = np.full((h, w), np.nan, dtype="float32")
    reproject(source=coarse, destination=base,
              src_transform=coarse_tf, src_crs=crs,
              dst_transform=transform, dst_crs=crs,
              resampling=Resampling.bilinear)
    relative = (z - base).astype("float32")
    from ._terrain import hillshade

    shade = hillshade(z, pixel)

    if clip is None:
        clip = a.clip_default
    if clip and a.geometry is not None:
        for arr in (relative, z, base, shade):
            mask_to_geometry(arr, a.geometry, transform, crs)

    attrs = {**dem.attrs, "river": river_name, "river_source": river_source,
             "n_river_samples": int(len(zs)), "idw_k": k, "idw_power": power}
    return xr.Dataset(
        {"rem": dem.copy(data=relative).rename("rem"),
         "dem": dem.copy(data=z).rename("dem"),
         "water_surface": dem.copy(data=base).rename("water_surface"),
         "hillshade": dem.copy(data=shade).rename("hillshade")},
        attrs=attrs,
    )
