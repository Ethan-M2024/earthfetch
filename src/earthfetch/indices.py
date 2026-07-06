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
    "ndmi": ("B08", "B11"),
    "ndsi": ("B03", "B11"),
    "ndre": ("B08", "B05"),
    "ndbi": ("B11", "B08"),
    "gndvi": ("B08", "B03"),
    "msavi": ("B08", "B04"),
    "bsi": ("B11", "B04", "B08", "B02"),
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


def normalized_difference(obj, band_a: str, band_b: str, name: str = "nd"):
    """Generic normalized difference ``(A - B)/(A + B)`` for any two bands.

    Escape hatch beyond the twelve named indices, e.g.
    ``normalized_difference(ds, "B03", "B08", name="ndwi")``.
    """
    a, b = _band(obj, band_a), _band(obj, band_b)
    return ((a - b) / (a + b)).rename(name)


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


def ndmi(obj):
    """Normalized Difference Moisture Index: (NIR - SWIR1)/(NIR + SWIR1)."""
    nir, swir1 = _band(obj, "B08"), _band(obj, "B11")
    return ((nir - swir1) / (nir + swir1)).rename("ndmi")


def ndsi(obj):
    """Normalized Difference Snow Index: (G - SWIR1)/(G + SWIR1)."""
    green, swir1 = _band(obj, "B03"), _band(obj, "B11")
    return ((green - swir1) / (green + swir1)).rename("ndsi")


def ndre(obj):
    """Normalized Difference Red Edge: (NIR - RE1)/(NIR + RE1)."""
    nir, re1 = _band(obj, "B08"), _band(obj, "B05")
    return ((nir - re1) / (nir + re1)).rename("ndre")


def ndbi(obj):
    """Normalized Difference Built-up Index: (SWIR1 - NIR)/(SWIR1 + NIR)."""
    swir1, nir = _band(obj, "B11"), _band(obj, "B08")
    return ((swir1 - nir) / (swir1 + nir)).rename("ndbi")


def gndvi(obj):
    """Green NDVI: (NIR - G)/(NIR + G)."""
    nir, green = _band(obj, "B08"), _band(obj, "B03")
    return ((nir - green) / (nir + green)).rename("gndvi")


def msavi(obj):
    """Modified Soil-Adjusted Vegetation Index (needs reflectance)."""
    import numpy as np

    nir, red = _band(obj, "B08"), _band(obj, "B04")
    return (
        (2 * nir + 1 - np.sqrt((2 * nir + 1) ** 2 - 8 * (nir - red))) / 2
    ).rename("msavi")


def bsi(obj):
    """Bare Soil Index: ((SWIR1 + R) - (NIR + B)) / ((SWIR1 + R) + (NIR + B))."""
    swir1, red = _band(obj, "B11"), _band(obj, "B04")
    nir, blue = _band(obj, "B08"), _band(obj, "B02")
    return (
        ((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue))
    ).rename("bsi")


INDICES = {
    "ndvi": ndvi, "ndwi": ndwi, "nbr": nbr, "evi": evi, "savi": savi,
    "ndmi": ndmi, "ndsi": ndsi, "ndre": ndre, "ndbi": ndbi,
    "gndvi": gndvi, "msavi": msavi, "bsi": bsi,
}
