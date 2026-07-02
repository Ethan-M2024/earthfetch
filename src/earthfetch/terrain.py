"""Terrain derivatives from DEMs: slope, aspect, hillshade.

Requires the ``xarray`` extra. Gradients need metric pixels, so the
default CRS is the AOI's UTM zone.
"""

from __future__ import annotations

import numpy as np

from .aoi import resolve_aoi, resolve_crs
from .raster import make_grid, mask_to_geometry
from .utils import logger

PRODUCTS = ("dem", "slope", "aspect", "hillshade")


def _gradients(dem: np.ndarray, res: float):
    """dz/dx (east) and dz/dy (north) for a north-up grid (rows go south)."""
    d_row, d_col = np.gradient(dem, res)
    return d_col, -d_row


def slope_aspect(dem: np.ndarray, res: float):
    """Slope and aspect in degrees. Aspect is compass-style: 0=N, 90=E."""
    dz_dx, dz_dy = _gradients(dem, res)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    aspect = (np.degrees(np.arctan2(dz_dx, dz_dy)) + 180.0) % 360.0
    return slope.astype("float32"), aspect.astype("float32")


def hillshade(
    dem: np.ndarray, res: float, azimuth: float = 315.0, altitude: float = 45.0
) -> np.ndarray:
    """Illumination 0..255 for a light source at (azimuth, altitude) degrees."""
    dz_dx, dz_dy = _gradients(dem, res)
    slope_r = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect_r = np.arctan2(dz_dx, dz_dy)  # 0 = north, clockwise positive
    az = np.radians(azimuth)
    alt = np.radians(altitude)
    shaded = (np.sin(alt) * np.cos(slope_r)
              + np.cos(alt) * np.sin(slope_r) * np.cos(az - aspect_r))
    return (np.clip(shaded, 0, 1) * 255).astype("float32")


def terrain(
    aoi,
    products=("dem", "slope", "aspect", "hillshade"),
    resolution: str = "10m",
    crs: str = "utm",
    res: float = None,
    source: str = "auto",
    azimuth: float = 315.0,
    altitude: float = 45.0,
    clip: bool = None,
) -> "xarray.Dataset":
    """DEM + terrain derivatives for any AOI as an aligned Dataset.

    ``products`` chooses among "dem" (meters), "slope" (degrees), "aspect"
    (compass degrees), "hillshade" (0-255). Other args follow ``load_dem``.
    """
    unknown = set(products) - set(PRODUCTS)
    if unknown:
        raise ValueError(f"unknown products {sorted(unknown)}; pick from {PRODUCTS}")
    from .load import _xr, load_dem

    xr = _xr()
    a = resolve_aoi(aoi)
    crs = resolve_crs(crs, a.bbox)
    dem = load_dem(a.bbox, resolution=resolution, crs=crs, res=res, source=source)
    pixel = abs(dem.attrs["transform"][0])
    logger.info("terrain: %s at %.1f-unit pixels in %s", list(products), pixel, crs)

    layers = {"dem": dem.values}
    if "slope" in products or "aspect" in products:
        layers["slope"], layers["aspect"] = slope_aspect(dem.values, pixel)
    if "hillshade" in products:
        layers["hillshade"] = hillshade(dem.values, pixel, azimuth, altitude)

    if clip is None:
        clip = a.clip_default
    if clip and a.geometry is not None:
        transform, width, height = make_grid(a.bbox, crs, pixel)
        for arr in layers.values():
            mask_to_geometry(arr, a.geometry, transform, crs)

    ds = xr.Dataset(
        {name: dem.copy(data=layers[name]).rename(name)
         for name in products},
        attrs={**dem.attrs, "products": list(products)},
    )
    return ds
