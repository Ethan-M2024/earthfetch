"""Relative Elevation Models: terrain height above the nearby river.

A REM subtracts a water-surface estimate from the DEM, flattening the valley
so the river sits at zero and every terrace, abandoned channel, and flood-prone
swale shows up as height above the channel.

The default pipeline follows the Automated Relative Elevation Model Generator
(Muhlestein, University of Utah PSM thesis, sponsored by Kleinschmidt
Associates):

1. merge the centerline into one continuous channel and sample it every
   ``spacing`` meters of channel distance;
2. read the water surface as the median of a short cross-section at each
   sample, perpendicular to the flow;
3. drop bridge decks (points well above a rolling median), force the profile
   downhill (isotonic regression with a small tolerance for pools), and
   smooth it (Savitzky-Golay, window scaled to river size);
4. build the base surface by flow projection: every pixel is placed at a
   position along the channel (from the flow tangents of its nearest
   stations) and takes the profile elevation there, so the surface follows
   the valley down-slope without seams at bends or far from the river;
5. subtract.

``method="idw"`` swaps step 4 for detrended inverse-distance weighting.

Requires the ``xarray`` extra. Pure NumPy: no SciPy, no shapely.
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
_MAX_POINTS = 2_000
#: cross-section half-width by centerline source (meters). Mapped NHD lines
#: drift 5-30 m off the wetted channel; user lines are assumed on the thalweg
_HALF_WIDTH = {"nhd": 25.0, "osm": 25.0, "user": 7.5}


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


def _merge_lines(parts: list, tol: float) -> list:
    """Chain line pieces that share endpoints (NHD splits a river at every
    confluence) into continuous lines, longest first."""
    lines = [np.asarray(p, dtype="float64")[:, :2] for p in parts if len(p) >= 2]
    merged = []
    while lines:
        cur = lines.pop(0)
        grew = True
        while grew:
            grew = False
            for i, ln in enumerate(lines):
                if np.hypot(*(cur[-1] - ln[0])) <= tol:
                    cur = np.vstack([cur, ln[1:]])
                elif np.hypot(*(cur[-1] - ln[-1])) <= tol:
                    cur = np.vstack([cur, ln[::-1][1:]])
                elif np.hypot(*(cur[0] - ln[-1])) <= tol:
                    cur = np.vstack([ln, cur[1:]])
                elif np.hypot(*(cur[0] - ln[0])) <= tol:
                    cur = np.vstack([ln[::-1], cur[1:]])
                else:
                    continue
                lines.pop(i)
                grew = True
                break
        merged.append(cur)
    return sorted(merged, key=lambda ln: -np.hypot(*np.diff(ln, axis=0).T).sum())


def _clip_to_grid(line: np.ndarray, bounds) -> np.ndarray:
    """Longest run of vertices inside the grid (NHD features overhang the AOI)."""
    left, bottom, right, top = bounds
    inside = ((line[:, 0] >= left) & (line[:, 0] <= right)
              & (line[:, 1] >= bottom) & (line[:, 1] <= top))
    best, start = (0, 0), None
    for i, ok in enumerate(np.append(inside, False)):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return line[best[0]:best[1]]


def _stations(line: np.ndarray, spacing: float):
    """(points, channel distance) every ``spacing`` along a polyline."""
    seg = np.hypot(*np.diff(line, axis=0).T)
    dist = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(np.ceil(dist[-1] / spacing)) + 1)
    s = np.linspace(0.0, dist[-1], n)
    pts = np.column_stack([np.interp(s, dist, line[:, 0]),
                           np.interp(s, dist, line[:, 1])])
    return pts, s


def _tangents(pts: np.ndarray):
    """Unit flow tangents and left-hand normals at each station."""
    t = np.zeros_like(pts)
    if len(pts) >= 2:
        t[1:-1] = pts[2:] - pts[:-2]
        t[0] = pts[1] - pts[0]
        t[-1] = pts[-1] - pts[-2]
    norm = np.hypot(t[:, 0], t[:, 1])
    norm[norm == 0] = 1.0
    t = t / norm[:, None]
    return t, np.column_stack([-t[:, 1], t[:, 0]])


def _cross_section_median(dem, transform, pts, normals, half_width,
                          nsamples: int = 21) -> np.ndarray:
    """Water surface at each station: the median of a cross-section across
    the channel, which tolerates a centerline that sits off the thalweg."""
    offsets = np.linspace(-half_width, half_width, nsamples)
    xs = pts[:, 0, None] + offsets[None, :] * normals[:, 0, None]
    ys = pts[:, 1, None] + offsets[None, :] * normals[:, 1, None]
    cols, rows = ~transform * (xs, ys)
    rows = np.floor(rows).astype(int)
    cols = np.floor(cols).astype(int)
    h, w = dem.shape
    ok = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
    vals = np.full(xs.shape, np.nan)
    vals[ok] = dem[rows[ok], cols[ok]]
    enough = np.isfinite(vals).sum(axis=1) >= max(3, int(0.3 * nsamples))
    out = np.full(len(pts), np.nan)
    if enough.any():
        out[enough] = np.nanmedian(vals[enough], axis=1)
    return out


def _rolling_median(z: np.ndarray, window: int) -> np.ndarray:
    """Centered running median (edges use the shrunken window)."""
    half = window // 2
    padded = np.pad(z, half, mode="constant", constant_values=np.nan)
    view = np.lib.stride_tricks.sliding_window_view(padded, window)
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(view, axis=1)


def _drop_bridges(z: np.ndarray, threshold: float = 1.5, window: int = 15):
    """Mask of stations to keep: bridge decks and spikes sit well above the
    rolling median of the profile."""
    if z.size < window * 2:
        return np.ones(z.size, dtype=bool)
    return ~(z > _rolling_median(z, window) + threshold)


def _enforce_downhill(z: np.ndarray, tolerance: float = 0.5) -> np.ndarray:
    """Water flows downhill: the closest non-increasing profile to ``z``
    (isotonic regression, pool-adjacent-violators), after letting rises of up
    to ``tolerance`` (pools, riffle noise) stand.

    Averaging each run of violators, instead of clamping to the last good
    value, avoids the flat-then-cliff stairs that clamping leaves behind.
    """
    z = np.asarray(z, dtype="float64")
    vals, wts, sizes = [], [], []
    for v in z:
        vals.append(v)
        wts.append(1.0)
        sizes.append(1)
        while len(vals) > 1 and vals[-1] > vals[-2] + tolerance:
            w = wts[-1] + wts[-2]
            v = (vals[-1] * wts[-1] + vals[-2] * wts[-2]) / w
            n = sizes[-1] + sizes[-2]
            del vals[-2:], wts[-2:], sizes[-2:]
            vals.append(v)
            wts.append(w)
            sizes.append(n)
    return np.repeat(vals, sizes)


def _smoothing_window(length_m: float, spacing: float) -> float:
    """Profile smoothing window scaled to river size (larger rivers carry
    longer riffle-pool sequences): headwater <2 km, creek <10 km, small river
    <50 km, large river."""
    if length_m < 2_000:
        return max(100.0, spacing * 5)
    if length_m < 10_000:
        return max(400.0, spacing * 20)
    if length_m < 50_000:
        return max(800.0, spacing * 40)
    return max(1_500.0, spacing * 75)


def _savgol(z: np.ndarray, window: int, order: int = 2) -> np.ndarray:
    """Savitzky-Golay smoothing, with polynomial fits at the two ends."""
    if z.size < 5:
        return z
    window = min(window, z.size if z.size % 2 else z.size - 1)
    window = max(window, order + 2 + (order % 2 == 0))
    if window % 2 == 0:
        window += 1
    if window > z.size:
        return z
    half = window // 2
    x = np.arange(-half, half + 1)
    coeff = np.linalg.pinv(np.vander(x, order + 1, increasing=True))[0]
    out = np.convolve(z, coeff[::-1], mode="same")
    for sl in (slice(0, window), slice(z.size - window, z.size)):
        idx = np.arange(z.size)[sl]
        fit = np.polyval(np.polyfit(idx, z[sl], order), idx)
        edge = idx[:half] if sl.start == 0 else idx[-half:]
        out[edge] = fit[:half] if sl.start == 0 else fit[-half:]
    return out


def _knn(xy: np.ndarray, q: np.ndarray, k: int):
    """(distances, indices) of the k nearest stations to each query point."""
    k = min(k, len(xy))
    try:
        from scipy.spatial import cKDTree

        dist, idx = cKDTree(xy).query(q, k=k)
        if k == 1:
            dist, idx = dist[:, None], idx[:, None]
        return dist, idx
    except ImportError:
        dist = np.empty((len(q), k))
        idx = np.empty((len(q), k), dtype=int)
        step = max(1, 20_000_000 // max(1, len(xy)))
        for s in range(0, len(q), step):
            d = np.hypot(q[s:s + step, 0, None] - xy[None, :, 0],
                         q[s:s + step, 1, None] - xy[None, :, 1])
            part = np.argpartition(d, k - 1, axis=1)[:, :k] if k < len(xy) else \
                np.broadcast_to(np.arange(len(xy)), d.shape).copy()
            idx[s:s + step] = part
            dist[s:s + step] = np.take_along_axis(d, part, axis=1)
        return dist, idx


def _flow_weighted(xy, z, tangents, s, qx, qy, k: int = 16):
    """Base surface that follows the channel downstream.

    Each nearby station j estimates where a pixel sits along the river: its
    own channel distance plus the pixel's offset along its flow tangent,
    ``s_j + (p - x_j)·t_j``. Those estimates are averaged (inverse squared
    distance) and the pixel takes the river profile elevation at that channel
    position. Next to the river this is the cross-section the pixel is
    abreast of; far out on the floodplain every neighbour agrees on the
    position, so the surface stays continuous where a nearest-station blend
    would step.
    """
    q = np.column_stack([qx.ravel(), qy.ravel()])
    dist, idx = _knn(xy, q, k)
    along = ((q[:, None, 0] - xy[idx, 0]) * tangents[idx, 0]
             + (q[:, None, 1] - xy[idx, 1]) * tangents[idx, 1])
    w = 1.0 / np.maximum(dist, 1e-6) ** 2
    pos = (w * (s[idx] + along)).sum(axis=1) / w.sum(axis=1)
    return np.interp(pos, s, z).reshape(qx.shape)


def _idw(xy: np.ndarray, z: np.ndarray, qx: np.ndarray, qy: np.ndarray,
         power: float) -> np.ndarray:
    """Inverse-distance-weighted values over every station (seamless)."""
    q = np.column_stack([qx.ravel(), qy.ravel()])
    vals = np.empty(len(q))
    step = max(1, 20_000_000 // max(1, len(xy)))
    for s in range(0, len(q), step):
        d = np.hypot(q[s:s + step, 0, None] - xy[None, :, 0],
                     q[s:s + step, 1, None] - xy[None, :, 1])
        wts = 1.0 / np.maximum(d, 1e-6) ** power
        vals[s:s + step] = (wts @ z) / wts.sum(axis=1)
    return vals.reshape(qx.shape)


def _detrended_idw(xy, z, qx, qy, power: float):
    """IDW of residuals from a down-valley trend, plus the trend: plain IDW
    drifts to the mean river elevation far from the channel."""
    center = xy.mean(axis=0)
    _, spread, axes = np.linalg.svd(xy - center, full_matrices=False)
    uv = (xy - center) @ axes.T
    keep = [0] if spread[1] < 0.05 * spread[0] else [0, 1]
    design = np.column_stack([uv[:, keep], np.ones(len(z))])
    coef = np.linalg.lstsq(design, z, rcond=None)[0]
    lo, hi = uv[:, 0].min(), uv[:, 0].max()

    def trend(x, y):
        pts = np.stack([x - center[0], y - center[1]], axis=-1) @ axes.T
        pts[..., 0] = np.clip(pts[..., 0], lo, hi)
        return sum(coef[i] * pts[..., a] for i, a in enumerate(keep)) + coef[-1]

    resid = z - trend(xy[:, 0], xy[:, 1])
    return trend(qx, qy) + _idw(xy, resid, qx, qy, power)


def rem(
    aoi,
    river=None,
    resolution: str = "10m",
    crs: str = "utm",
    res: float | None = None,
    source: str = "auto",
    spacing: float = 20.0,
    method: str = "flow",
    half_width: float | None = None,
    smooth: float | None = None,
    power: float = 3.0,
    blend: float = 150.0,
    max_value: float | None = None,
    clip: bool | None = None,
) -> xarray.Dataset:
    """Relative Elevation Model for any AOI in one call.

    Downloads the DEM, finds the river (USGS NHD in the US, OpenStreetMap
    worldwide), reads its water surface from cross-sections, builds a
    flow-following base surface, and subtracts it: the whole floodplain
    mapping workflow.

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
    spacing : meters of channel between river stations.
    method : "flow" (flow-weighted, the default) or "idw" (detrended
        inverse-distance weighting over every station).
    half_width : cross-section half-width in meters (default 25 for mapped
        NHD/OSM lines, 7.5 for your own). Capped at 40% of ``spacing`` so
        neighbouring sections never overlap.
    smooth : profile smoothing window in meters (Savitzky-Golay). Default
        scales with the river length in the AOI (100 m to 1.5 km).
    power : IDW distance exponent.
    blend : ``method="flow"`` hands off from flow projection to detrended IDW
        over this distance from the channel (meters), so wide floodplains
        stay seamless between bends.
    max_value : NaN-out REM values above this height, e.g. 10 to map only
        the floodplain.
    clip : NaN-out pixels outside a polygon AOI.

    Returns
    -------
    xarray.Dataset
        ``rem`` (meters above the river), ``dem`` (meters), ``water_surface``
        (the base surface), and ``hillshade`` (0-255), all float32 on one
        grid. Attrs record the river name and centerline source. For the
        classic map: ``ef.preview(r.rem, "rem.png", cmap="YlGnBu_r", vmin=0,
        vmax=6, shade=r.hillshade)``.
    """
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject, transform_geom

    from ._terrain import hillshade
    from .load import _xr, load_dem
    from .raster import mask_to_geometry

    if method not in ("flow", "idw"):
        raise ValueError(f"method must be 'flow' or 'idw', got {method!r}")
    xr = _xr()
    a = resolve_aoi(aoi)
    crs = resolve_crs(crs, a.bbox)
    geom, river_name, river_source = _river_geometry(river, a)
    dem = load_dem(a.bbox, resolution=resolution, crs=crs, res=res, source=source)
    z = dem.values.astype("float32")
    transform = Affine(*dem.attrs["transform"])
    pixel = abs(transform.a)
    h, w = z.shape
    top, left = transform.f, transform.c
    bounds = (left, top + transform.e * h, left + transform.a * w, top)
    spacing = max(float(spacing), pixel)

    # 1. one continuous channel, stationed along its length
    projected = transform_geom("EPSG:4326", crs, geom)
    lines = [_clip_to_grid(ln, bounds)
             for ln in _merge_lines(_parts(projected), tol=max(1.0, pixel))]
    lines = [ln for ln in lines if len(ln) >= 2]
    if not lines:
        raise EarthfetchError(
            f"the river{f' {river_name!r}' if river_name else ''} does not "
            "cross the DEM; widen the AOI or pass river=<line>"
        )
    line = max(lines, key=lambda ln: np.hypot(*np.diff(ln, axis=0).T).sum())
    pts, s = _stations(line, spacing)

    # 2. water surface from perpendicular cross-sections
    _, normals = _tangents(pts)
    hw = half_width if half_width is not None else _HALF_WIDTH.get(river_source, 7.5)
    hw = max(min(hw, 0.4 * spacing), min(5.0, hw))
    prof = _cross_section_median(z, transform, pts, normals, hw)
    keep = np.isfinite(prof)
    if keep.sum() < 2:
        raise EarthfetchError("the river has no valid DEM cells under it")
    pts, s, prof = pts[keep], s[keep], prof[keep]

    # 3. clean the profile: bridges out, downhill only, smoothed
    keep = _drop_bridges(prof)
    pts, s, prof = pts[keep], s[keep], prof[keep]
    n = max(1, prof.size // 10)
    if np.median(prof[:n]) < np.median(prof[-n:]):   # orient upstream -> down
        pts, s, prof = pts[::-1], s[::-1], prof[::-1]
    prof = _enforce_downhill(prof)
    if smooth is None:
        smooth = _smoothing_window(float(abs(s[-1] - s[0])), spacing)
    win = max(5, int(round(float(smooth) / spacing)))
    prof = _savgol(prof, win + (win % 2 == 0))
    if len(prof) > _MAX_POINTS:
        pick = np.linspace(0, len(prof) - 1, _MAX_POINTS).astype(int)
        pts, s, prof = pts[pick], s[pick], prof[pick]
    s = np.abs(s - s[0])                           # channel distance downstream
    tangents, _ = _tangents(pts)
    logger.info("rem: %s (%s), %d stations every %.0f m, %.1f m cross-sections, %s",
                river_name or "river", river_source, len(prof), spacing, hw, method)

    # 4. base surface on a coarse grid, resampled to full resolution
    factor = max(1, int(np.ceil(np.sqrt(h * w / _BASE_CELLS))))
    ch, cw = int(np.ceil(h / factor)), int(np.ceil(w / factor))
    coarse_tf = transform * Affine.scale(factor)
    cols, rows = np.meshgrid(np.arange(cw) + 0.5, np.arange(ch) + 0.5)
    qx, qy = coarse_tf * (cols, rows)
    if method == "flow":
        # flow projection is exact beside the channel but seams between bends
        # far out on a wide floodplain, where the IDW surface is continuous;
        # hand off between them with distance from the river
        near = _flow_weighted(pts, prof, tangents, s, qx, qy)
        far = _detrended_idw(pts, prof, qx, qy, power)
        d = _knn(pts, np.column_stack([qx.ravel(), qy.ravel()]), 1)[0][:, 0]
        alpha = np.exp(-((d / blend) ** 2)).reshape(qx.shape)
        coarse = alpha * near + (1 - alpha) * far
    else:
        coarse = _detrended_idw(pts, prof, qx, qy, power)
    base = np.full((h, w), np.nan, dtype="float32")
    reproject(source=coarse.astype("float32"), destination=base,
              src_transform=coarse_tf, src_crs=crs,
              dst_transform=transform, dst_crs=crs,
              resampling=Resampling.bilinear)

    # 5. subtract
    relative = (z - base).astype("float32")
    if max_value is not None:
        relative[relative > float(max_value)] = np.nan
    shade = hillshade(z, pixel)

    if clip is None:
        clip = a.clip_default
    if clip and a.geometry is not None:
        for arr in (relative, z, base, shade):
            mask_to_geometry(arr, a.geometry, transform, crs)

    attrs = {**dem.attrs, "river": river_name, "river_source": river_source,
             "method": method, "n_river_samples": int(len(prof)),
             "spacing_m": spacing, "cross_section_half_width_m": hw}
    return xr.Dataset(
        {"rem": dem.copy(data=relative).rename("rem"),
         "dem": dem.copy(data=z).rename("dem"),
         "water_surface": dem.copy(data=base).rename("water_surface"),
         "hillshade": dem.copy(data=shade).rename("hillshade")},
        attrs=attrs,
    )
