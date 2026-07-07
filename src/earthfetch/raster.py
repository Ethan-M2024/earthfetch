"""Raster ops: windowed COG reads, grid warping, clip + reproject.

Requires the ``raster`` extra: ``pip install earthfetch[raster]``.
Remote URLs are read with HTTP range requests — only the bbox window
travels over the network, never the whole file.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from .exceptions import MissingDependencyError
from .utils import logger, redact_url, validate_bbox

try:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.errors import WindowError
    from rasterio.merge import merge as rio_merge
    from rasterio.transform import Affine, array_bounds, from_origin
    from rasterio.warp import calculate_default_transform, reproject, transform_bounds
    from rasterio.windows import Window
    from rasterio.windows import from_bounds as window_from_bounds
except ImportError as exc:  # pragma: no cover
    raise MissingDependencyError(
        "rasterio is required for raster operations: pip install earthfetch[raster]"
    ) from exc

#: GDAL settings that make remote COG reads fast
_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "AWS_NO_SIGN_REQUEST": "YES",
}


def make_grid(
    bbox: Sequence[float], crs: str, res: float
) -> tuple[rasterio.Affine, int, int]:
    """Target grid (transform, width, height) for a WGS84 bbox in ``crs``
    at ``res`` (units of ``crs``: meters for projected, degrees for geographic).
    """
    bbox = validate_bbox(bbox)
    minx, miny, maxx, maxy = transform_bounds("EPSG:4326", crs, *bbox)
    width = max(1, math.ceil((maxx - minx) / res))
    height = max(1, math.ceil((maxy - miny) / res))
    return from_origin(minx, maxy, res, res), width, height


def warp_into_grid(
    sources: Sequence[str | os.PathLike],
    transform: rasterio.Affine,
    width: int,
    height: int,
    crs: str,
    band: int = 1,
    dtype: str = "float32",
    nodata: float = float("nan"),
    resampling: Resampling = None,
) -> np.ndarray:
    """Read one band from each source (local path or remote COG URL),
    windowed to the target grid's footprint, and mosaic into one array.

    Remote sources are read via HTTP range requests — only the needed
    window is transferred. Sources may be in different CRSs.
    """
    if resampling is None:
        resampling = Resampling.bilinear
    dst = np.full((height, width), nodata, dtype=dtype)
    dst_bounds = array_bounds(height, width, transform)

    with rasterio.Env(**_ENV):
        for src in sources:
            with rasterio.open(src) as ds:
                try:
                    src_bounds = transform_bounds(crs, ds.crs, *dst_bounds)
                    win = window_from_bounds(*src_bounds, ds.transform)
                    # pad 2 px for resampling kernels, clamp to the dataset
                    win = Window(win.col_off - 2, win.row_off - 2,
                                 win.width + 4, win.height + 4)
                    win = win.intersection(Window(0, 0, ds.width, ds.height))
                except WindowError:
                    logger.debug("source outside grid, skipping: %s",
                                 redact_url(str(src)))
                    continue
                if win.width <= 0 or win.height <= 0:
                    continue
                # decimate the read to ~2x the target resolution so GDAL
                # serves it from overviews — reading 0.6 m NAIP at native
                # res for a 30 m grid transfers 2500x more than needed
                grid_px_in_src = (src_bounds[2] - src_bounds[0]) / width
                factor = max(1.0, grid_px_in_src / ds.res[0] / 2.0)
                out_h = max(1, round(win.height / factor))
                out_w = max(1, round(win.width / factor))
                data = ds.read(band, window=win, out_shape=(out_h, out_w))
                src_transform = ds.window_transform(win) * Affine.scale(
                    win.width / out_w, win.height / out_h
                )
                logger.debug("read %dx%d (of %dx%d) from %s",
                             out_w, out_h, win.width, win.height,
                             redact_url(str(src)))
                reproject(
                    source=data,
                    destination=dst,
                    src_transform=src_transform,
                    src_crs=ds.crs,
                    dst_transform=transform,
                    dst_crs=crs,
                    src_nodata=ds.nodata,
                    dst_nodata=nodata,
                    resampling=resampling,
                    init_dest_nodata=False,
                )
    return dst


def mask_to_geometry(
    data: np.ndarray,
    geometry: dict,
    transform: rasterio.Affine,
    crs: str,
    nodata: float = float("nan"),
) -> np.ndarray:
    """Set pixels outside a WGS84 GeoJSON geometry to ``nodata`` (in place)."""
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom

    geom = transform_geom("EPSG:4326", crs, geometry)
    shape = data.shape[-2:]
    outside = geometry_mask([geom], out_shape=shape, transform=transform,
                            invert=False)
    data[..., outside] = nodata
    return data


def write_geotiff(
    path: str | os.PathLike,
    data: np.ndarray,
    transform: rasterio.Affine,
    crs: str,
    nodata: float | None = None,
    tags: dict | None = None,
) -> Path:
    """Write a (bands, y, x) or (y, x) array as a tiled, compressed GeoTIFF
    with provenance tags (source URLs, earthfetch version).
    """
    from . import __version__

    if data.ndim == 2:
        data = data[np.newaxis]
    count, height, width = data.shape
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff", "count": count, "dtype": data.dtype.name,
        "crs": crs, "transform": transform, "width": width, "height": height,
        "nodata": nodata, "compress": "deflate", "tiled": True,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)
        dst.update_tags(EARTHFETCH_VERSION=__version__, **(tags or {}))
    return path


def clip_reproject(
    paths: Sequence[str | os.PathLike],
    bbox: Sequence[float],
    dst_crs: str = "EPSG:4326",
    out_path: str | os.PathLike = "clipped.tif",
    resampling: Resampling = None,
) -> Path:
    """Merge raster tiles, clip to a WGS84 bbox, reproject to ``dst_crs``.

    Parameters
    ----------
    paths : one or more GeoTIFFs sharing a CRS (e.g. DEM tiles, one S2 band).
    bbox : (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees.
    dst_crs : any CRS string pyproj understands ("EPSG:32612", "EPSG:5070"...).
    out_path : output GeoTIFF path.

    Returns
    -------
    pathlib.Path
        The output GeoTIFF path.
    """
    if resampling is None:
        resampling = Resampling.bilinear
    bbox = validate_bbox(bbox)
    if not paths:
        raise ValueError("no input rasters given")

    datasets = [rasterio.open(p) for p in paths]
    try:
        src_crs = datasets[0].crs
        src_bounds = transform_bounds("EPSG:4326", src_crs, *bbox)
        data, src_transform = rio_merge(datasets, bounds=src_bounds)
        count, height, width = data.shape
        nodata = datasets[0].nodata
    finally:
        for ds in datasets:
            ds.close()

    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs, width, height, *src_bounds
    )
    out = np.full((count, dst_height, dst_width),
                  nodata if nodata is not None else 0, dtype=data.dtype)
    for b in range(count):
        reproject(
            source=data[b], destination=out[b],
            src_transform=src_transform, src_crs=src_crs,
            dst_transform=dst_transform, dst_crs=dst_crs,
            src_nodata=nodata, dst_nodata=nodata, resampling=resampling,
        )
    return write_geotiff(
        out_path, out, dst_transform, dst_crs, nodata=nodata,
        tags={"EARTHFETCH_SOURCES": ",".join(str(p) for p in paths)},
    )
