"""Export earthfetch xarray results: GeoTIFF, COG, quick-look PNG.

Requires the ``raster`` extra (rasterio). Works on any DataArray/Dataset
produced by ``load_*``, ``stack``, ``composite``, ``terrain``, or indices
applied to them — the CRS/transform ride along in ``attrs``.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .exceptions import EarthfetchError

try:
    import rasterio
    from rasterio.transform import Affine
except ImportError as exc:  # pragma: no cover
    from .exceptions import MissingDependencyError

    raise MissingDependencyError(
        "rasterio is required for export: pip install earthfetch[raster]"
    ) from exc


def _georef(obj):
    attrs = obj.attrs
    if "transform" not in attrs or "crs" not in attrs:
        # index results inherit coords but xarray ops can drop attrs;
        # fall back to reconstructing the transform from coords
        try:
            xs = obj["x"].values
            ys = obj["y"].values
            rx = float(xs[1] - xs[0])
            ry = float(ys[1] - ys[0])
            transform = Affine(rx, 0, float(xs[0]) - rx / 2,
                               0, ry, float(ys[0]) - ry / 2)
            crs = attrs.get("crs")
            if crs:
                return transform, crs
        except Exception:
            pass
        raise EarthfetchError(
            "object lacks crs/transform attrs; pass one produced by "
            "earthfetch, or copy attrs from its source (e.g. "
            "ndvi.attrs = ds.attrs)"
        )
    return Affine(*attrs["transform"]), attrs["crs"]


def _to_3d(obj) -> np.ndarray:
    data = np.asarray(obj.values if hasattr(obj, "values") else obj,
                      dtype="float32")
    return data[np.newaxis] if data.ndim == 2 else data


def _collect(obj):
    """(3D array, band names, transform, crs) from a DataArray or Dataset."""
    if hasattr(obj, "data_vars"):  # Dataset
        names = list(obj.data_vars)
        transform, crs = _georef_ds(obj)
        data = np.stack([np.asarray(obj[n].values, dtype="float32") for n in names])
        return data, names, transform, crs
    transform, crs = _georef(obj)
    data = _to_3d(obj)
    if "band" in getattr(obj, "coords", {}):
        names = [str(b) for b in obj.band.values]
    else:
        names = [obj.name or "band1"] if data.shape[0] == 1 else [
            f"band{i+1}" for i in range(data.shape[0])
        ]
    return data, names, transform, crs


def _georef_ds(ds):
    if "transform" in ds.attrs and "crs" in ds.attrs:
        return Affine(*ds.attrs["transform"]), ds.attrs["crs"]
    first = ds[list(ds.data_vars)[0]]
    return _georef(first)


def _write(path, data, names, transform, crs, driver_opts):
    from . import __version__

    count, height, width = data.shape
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "count": count, "dtype": "float32", "crs": crs,
        "transform": transform, "width": width, "height": height,
        "nodata": np.nan, **driver_opts,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)
        for i, name in enumerate(names, start=1):
            dst.set_band_description(i, name)
        dst.update_tags(EARTHFETCH_VERSION=__version__)
    return path


def to_geotiff(obj, path: str | os.PathLike) -> Path:
    """Write a DataArray/Dataset as a tiled, deflate-compressed GeoTIFF."""
    data, names, transform, crs = _collect(obj)
    return _write(path, data, names, transform, crs,
                  {"driver": "GTiff", "compress": "deflate", "tiled": True})


def to_cog(obj, path: str | os.PathLike) -> Path:
    """Write a DataArray/Dataset as a Cloud-Optimized GeoTIFF."""
    data, names, transform, crs = _collect(obj)
    return _write(path, data, names, transform, crs,
                  {"driver": "COG", "compress": "deflate"})


def preview(obj, path: str | os.PathLike = "preview.png",
            stretch: tuple = (2, 98)) -> Path:
    """Quick-look PNG with a percentile stretch.

    3-band inputs (e.g. B04,B03,B02 composites) render as RGB; single bands
    as grayscale. Returns the PNG path — open it, or embed it in a notebook.
    """
    data, _, transform, crs = _collect(obj)
    if data.shape[0] not in (1, 3):
        data = data[:3]
    out = np.zeros_like(data, dtype="uint8")
    for i, band in enumerate(data):
        finite = band[np.isfinite(band)]
        if finite.size == 0:
            continue
        lo, hi = np.percentile(finite, stretch)
        scaled = (band - lo) / (hi - lo) if hi > lo else band * 0
        out[i] = (np.clip(np.nan_to_num(scaled), 0, 1) * 255).astype("uint8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count, height, width = out.shape
    with rasterio.open(path, "w", driver="PNG", count=count, dtype="uint8",
                       width=width, height=height) as dst:
        dst.write(out)
    return path
