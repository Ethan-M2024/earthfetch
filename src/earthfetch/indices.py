"""Spectral indices for Sentinel-2 reflectance data.

Each function accepts an ``xarray.Dataset`` (band-named variables, as from
``stack``/``composite``) or a ``DataArray`` with a ``band`` coordinate (as
from ``load_sentinel2``). Inputs should be reflectance (the default
``scale=True`` in loaders); ratio indices tolerate raw DNs approximately.
"""

from __future__ import annotations

from .exceptions import BandNotFoundError

#: index name -> required ESA bands
INDEX_BANDS = {
    "ndvi": ("B08", "B04"),
    "ndwi": ("B03", "B08"),
    "nbr": ("B08", "B12"),
    "evi": ("B08", "B04", "B02"),
    "savi": ("B08", "B04"),
}


def _band(obj, name: str):
    if hasattr(obj, "data_vars"):  # Dataset
        if name in obj:
            return obj[name]
        raise BandNotFoundError(
            f"variable {name!r} not in Dataset; have {list(obj.data_vars)}"
        )
    bands = [str(b) for b in obj.band.values]
    if name not in bands:
        raise BandNotFoundError(f"band {name!r} not in DataArray; have {bands}")
    return obj.sel(band=name)


def ndvi(obj):
    """Normalized Difference Vegetation Index: (NIR - Red)/(NIR + Red)."""
    nir, red = _band(obj, "B08"), _band(obj, "B04")
    return ((nir - red) / (nir + red)).rename("ndvi")


def ndwi(obj):
    """Normalized Difference Water Index (McFeeters): (G - NIR)/(G + NIR)."""
    green, nir = _band(obj, "B03"), _band(obj, "B08")
    return ((green - nir) / (green + nir)).rename("ndwi")


def nbr(obj):
    """Normalized Burn Ratio: (NIR - SWIR2)/(NIR + SWIR2)."""
    nir, swir2 = _band(obj, "B08"), _band(obj, "B12")
    return ((nir - swir2) / (nir + swir2)).rename("nbr")


def evi(obj):
    """Enhanced Vegetation Index (needs reflectance, not raw DNs)."""
    nir, red, blue = _band(obj, "B08"), _band(obj, "B04"), _band(obj, "B02")
    return (2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)).rename("evi")


def savi(obj, soil_factor: float = 0.5):
    """Soil-Adjusted Vegetation Index (needs reflectance)."""
    nir, red = _band(obj, "B08"), _band(obj, "B04")
    lf = soil_factor
    return ((1 + lf) * (nir - red) / (nir + red + lf)).rename("savi")


INDICES = {"ndvi": ndvi, "ndwi": ndwi, "nbr": nbr, "evi": evi, "savi": savi}
