"""earthfetch: USGS 3DEP DEMs and Sentinel-2 L2A imagery, zero API keys.

Core (requests only): search + download functions.
``earthfetch[raster]``: clip_reproject, windowed reads.
``earthfetch[xarray]``: load_dem, load_sentinel2, stack — bbox in, array out.
"""

from .copernicus import copernicus_dem_urls, download_copernicus_dem
from .exceptions import (
    BandNotFoundError,
    DownloadError,
    EarthfetchError,
    MissingDependencyError,
    NoScenesError,
    TileNotFoundError,
)
from .sentinel import (
    BAND_ALIASES,
    BAND_RESOLUTION,
    band_url,
    clearest_scene,
    download_sentinel2,
    scene_summary,
    search_sentinel2,
)
from .usgs import DEM_DATASETS, dem_tile_urls, download_dem, search_dem
from .aoi import AOI, geocode, resolve_aoi, utm_crs
from .naip import naip_tile_urls, search_naip

__version__ = "0.4.0"

#: Lazily-imported names that need the raster/xarray extras
_LAZY = {
    "clip_reproject": "raster",
    "make_grid": "raster",
    "warp_into_grid": "raster",
    "write_geotiff": "raster",
    "load_dem": "load",
    "load_sentinel2": "load",
    "stack": "load",
    "composite": "composite",
    "terrain": "terrain",
    "slope_aspect": "terrain",
    "hillshade": "terrain",
    "ndvi": "indices",
    "ndwi": "indices",
    "nbr": "indices",
    "evi": "indices",
    "savi": "indices",
    "INDICES": "indices",
    "load_naip": "naip",
    "to_geotiff": "export",
    "to_cog": "export",
    "preview": "export",
}


def __getattr__(name):
    if name in _LAZY:
        import importlib

        mod = importlib.import_module(f".{_LAZY[name]}", __name__)
        obj = getattr(mod, name)
        # cache the resolved object; without this, functions sharing a
        # submodule's name (composite, terrain) resolve to the module on
        # the next access, because importing sets it as a package attr
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # search / download (core)
    "search_dem", "download_dem", "dem_tile_urls",
    "copernicus_dem_urls", "download_copernicus_dem",
    "search_sentinel2", "download_sentinel2", "clearest_scene",
    "scene_summary", "band_url",
    # arrays (extras)
    "load_dem", "load_sentinel2", "stack", "clip_reproject",
    "composite", "terrain", "load_naip", "search_naip",
    "ndvi", "ndwi", "nbr", "evi", "savi",
    "to_geotiff", "to_cog", "preview",
    # aoi
    "AOI", "resolve_aoi", "geocode", "utm_crs",
    # metadata
    "DEM_DATASETS", "BAND_ALIASES", "BAND_RESOLUTION",
    # exceptions
    "EarthfetchError", "DownloadError", "TileNotFoundError",
    "NoScenesError", "BandNotFoundError", "MissingDependencyError",
]
