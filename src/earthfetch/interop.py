"""Interoperability with the rioxarray / rasterio ecosystem.

earthfetch results carry their CRS and transform in ``.attrs``. These
helpers attach them to the object as a first-class georeference so the
``.rio`` accessor — ``.rio.reproject``, ``.rio.clip``, ``.rio.to_raster``,
``.rio.reproject_match`` — works, letting earthfetch arrays drop straight
into existing rioxarray workflows.

Requires the ``interop`` extra: ``pip install earthfetch[interop]``.
"""

from __future__ import annotations

from .exceptions import EarthfetchError, MissingDependencyError


def _rioxarray():
    try:
        import rioxarray  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise MissingDependencyError(
            "rioxarray is required for interop: pip install earthfetch[interop]"
        ) from exc


def _crs_of(obj) -> str:
    crs = obj.attrs.get("crs")
    if not crs:
        raise EarthfetchError(
            "object has no 'crs' attr; pass a DataArray/Dataset produced by "
            "earthfetch (load_*, composite, terrain, time_series, indices)"
        )
    return crs


def to_rioxarray(obj):
    """Attach the earthfetch CRS/transform so the ``.rio`` accessor works.

    Returns the same object with its CRS written; rioxarray infers the
    transform from the ``x``/``y`` coordinates. After this you can call any
    ``.rio`` method::

        da = ef.to_rioxarray(ef.composite("Moab, Utah", ...))
        da.rio.to_raster("moab.tif")
        da.rio.reproject("EPSG:4326")
    """
    _rioxarray()
    return obj.rio.write_crs(_crs_of(obj))


def reproject(obj, dst_crs: str, resolution: float | None = None,
              resampling: str = "bilinear"):
    """Reproject a DataArray/Dataset to ``dst_crs`` (via rioxarray).

    Parameters
    ----------
    obj : an earthfetch result (CRS taken from ``attrs``).
    dst_crs : target CRS, e.g. "EPSG:4326" or "EPSG:5070".
    resolution : output pixel size in ``dst_crs`` units; None keeps the
        source resolution reprojected.
    resampling : "nearest", "bilinear", "cubic", "average", ... (rasterio).

    Returns
    -------
    xarray.DataArray or xarray.Dataset
        The reprojected object, with a working ``.rio`` accessor.
    """
    _rioxarray()
    from rasterio.enums import Resampling

    how = getattr(Resampling, resampling)
    src = obj.rio.write_crs(_crs_of(obj))
    return src.rio.reproject(dst_crs, resolution=resolution, resampling=how)
