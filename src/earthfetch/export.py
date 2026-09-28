"""Export earthfetch xarray results: GeoTIFF, COG, quick-look PNG.

Requires the ``raster`` extra (rasterio). Works on any DataArray/Dataset
produced by ``load_*``, ``stack``, ``composite``, ``terrain``, or indices
applied to them — the CRS/transform ride along in ``attrs``.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np

from .exceptions import EarthfetchError

try:
    import rasterio
    from rasterio.errors import NotGeoreferencedWarning
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
        # a single selected band (obj.sel(band=...)) leaves a 0-d coord
        names = [str(b) for b in np.atleast_1d(obj.band.values)]
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


def _stretch_rgb(data: np.ndarray, stretch: tuple) -> np.ndarray:
    """Percentile-stretch a (bands, y, x) float array to 0..1 for display.

    Uses a single low/high computed across all bands together, so the colour
    balance between channels is preserved. Stretching each band to its own
    full range independently casts false colour on uniform or extreme scenes
    — a red desert turns rainbow, a mostly-black ocean over-saturates — which
    is exactly what a natural-colour quick-look must not do.
    """
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros_like(data, dtype="float32")
    lo, hi = np.percentile(finite, stretch)
    if hi <= lo:
        return np.zeros_like(data, dtype="float32")
    return np.clip(np.nan_to_num((data - lo) / (hi - lo)), 0, 1).astype("float32")


def show(obj, ax=None, cmap: str = "viridis", stretch: tuple = (2, 98),
         title: str | None = None, colorbar: bool = True):
    """Render a result inline with matplotlib — no file needed.

    3-band inputs display as a percentile-stretched RGB; single bands (and
    indices) as a colormapped image with a colorbar. Axes are in the data's
    CRS units. Returns the matplotlib ``Axes``.

    Requires the ``plot`` extra: ``pip install earthfetch[plot]``.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        from .exceptions import MissingDependencyError

        raise MissingDependencyError(
            "matplotlib is required for show(): pip install earthfetch[plot]"
        ) from exc

    data, names, transform, _ = _collect(obj)
    left, top = transform.c, transform.f
    right = left + transform.a * data.shape[-1]
    bottom = top + transform.e * data.shape[-2]
    extent = (left, right, bottom, top)
    if ax is None:
        _, ax = plt.subplots()

    if data.shape[0] >= 3:
        rgb = _stretch_rgb(data[:3], stretch)
        ax.imshow(np.moveaxis(rgb, 0, -1), extent=extent)
    else:
        band = data[0]
        finite = band[np.isfinite(band)]
        vlo, vhi = (np.percentile(finite, stretch) if finite.size
                    else (0, 1))
        im = ax.imshow(band, extent=extent, cmap=cmap, vmin=vlo, vmax=vhi)
        if colorbar:
            ax.figure.colorbar(im, ax=ax, shrink=0.8,
                               label=names[0] if names else "")
    ax.set_title(title if title is not None
                 else getattr(obj, "name", None) or "")
    return ax


def _colormap(band: np.ndarray, cmap: str, vmin, vmax, stretch) -> np.ndarray:
    """Single band -> (3, y, x) 0..1 RGB through a matplotlib colormap."""
    try:
        import matplotlib
    except ImportError as exc:  # pragma: no cover
        from .exceptions import MissingDependencyError

        raise MissingDependencyError(
            "matplotlib is required for preview(cmap=...): "
            "pip install earthfetch[plot]"
        ) from exc
    finite = band[np.isfinite(band)]
    lo, hi = (np.percentile(finite, stretch) if finite.size else (0.0, 1.0))
    lo = lo if vmin is None else vmin
    hi = hi if vmax is None else vmax
    norm = np.clip((band - lo) / ((hi - lo) or 1.0), 0, 1)
    rgb = matplotlib.colormaps[cmap](np.nan_to_num(norm))[..., :3]
    rgb[~np.isfinite(band)] = 1.0  # nodata renders white
    return np.moveaxis(rgb, -1, 0).astype("float32"), float(lo), float(hi)


def _legend_label(obj) -> str:
    name = getattr(obj, "name", None) or ""
    if name == "rem":
        return "Height above river (m)"
    units = getattr(obj, "attrs", {}).get("units")
    return f"{name} ({units})" if name and units else name or (units or "")


def _write_with_legend(path, rgb, cmap, lo, hi, label, data):
    """PNG of the map at full resolution with a labeled colorbar panel on
    the right. Colors past either end are marked with an arrow tip."""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    _, h, w = rgb.shape
    finite = data[np.isfinite(data)]
    extend = {(False, False): "neither", (True, False): "min",
              (False, True): "max", (True, True): "both"}[
        (bool(finite.size and finite.min() < lo), bool(finite.size and finite.max() > hi))]
    font = max(10.0, h / 70.0)
    panel = int(font * 9)
    dpi = 100
    fig = plt.figure(figsize=((w + panel) / dpi, h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, w / (w + panel), 1])
    ax.imshow(np.moveaxis(rgb, 0, -1), interpolation="nearest")
    ax.set_axis_off()
    cax = fig.add_axes([(w + font * 1.5) / (w + panel), 0.2,
                        font * 1.6 / (w + panel), 0.6])
    sm = plt.cm.ScalarMappable(norm=Normalize(lo, hi), cmap=cmap)
    bar = fig.colorbar(sm, cax=cax, extend=extend)
    bar.ax.tick_params(labelsize=font)
    bar.set_label(label, fontsize=font * 1.1)
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)


def preview(obj, path: str | os.PathLike = "preview.png",
            stretch: tuple = (2, 98), cmap: str | None = None,
            vmin: float | None = None, vmax: float | None = None,
            shade=None, legend: bool | str = False) -> Path:
    """Quick-look PNG with a percentile stretch.

    3-band inputs (e.g. B04,B03,B02 composites) render as RGB; single bands
    as grayscale, or through a matplotlib ``cmap`` ("YlGnBu_r", "terrain",
    ...) with optional fixed ``vmin``/``vmax``. ``shade`` takes a hillshade
    on the same grid (``terrain(...).hillshade``) and blends it in for
    relief — the classic look for Relative Elevation Models. ``legend=True``
    (with a ``cmap``) adds a colorbar panel labeled in the data's units,
    "Height above river (m)" for a REM; pass a string for your own label.
    Returns the PNG path — open it, or embed it in a notebook.
    """
    data, _, transform, crs = _collect(obj)
    if legend and cmap is None:
        raise EarthfetchError("legend needs a cmap, e.g. cmap='YlGnBu_r'")
    if cmap is not None:
        rgb, lo, hi = _colormap(data[0], cmap, vmin, vmax, stretch)
    else:
        if data.shape[0] not in (1, 3):
            data = data[:3]
        rgb = _stretch_rgb(data, stretch)
    if shade is not None:
        hs = np.asarray(getattr(shade, "values", shade), dtype="float32")
        if hs.shape != rgb.shape[-2:]:
            raise EarthfetchError(
                f"shade grid {hs.shape} does not match the image {rgb.shape[-2:]}"
            )
        hs = np.nan_to_num(hs / 255.0, nan=1.0)
        rgb = rgb * (0.45 + 0.55 * hs)  # soft multiply keeps colors readable
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if legend:
        label = legend if isinstance(legend, str) else _legend_label(obj)
        _write_with_legend(path, np.clip(rgb, 0, 1), cmap, lo, hi, label, data[0])
        return path
    out = (np.clip(rgb, 0, 1) * 255).astype("uint8")
    count, height, width = out.shape
    with warnings.catch_warnings():  # a PNG quick-look carries no georef
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(path, "w", driver="PNG", count=count, dtype="uint8",
                           width=width, height=height) as dst:
            dst.write(out)
    return path
