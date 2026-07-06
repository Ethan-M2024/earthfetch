"""earthfetch: USGS 3DEP DEMs and Sentinel-2 L2A imagery, zero API keys.

Core (requests only): search + download functions.
``earthfetch[raster]``: clip_reproject, windowed reads.
``earthfetch[xarray]``: load_dem, load_sentinel2, stack — bbox in, array out.
"""

from .aoi import AOI, geocode, resolve_aoi, utm_crs
from .copernicus import copernicus_dem_urls, download_copernicus_dem
from .exceptions import (
    BandNotFoundError,
    DownloadError,
    EarthfetchError,
    MissingDependencyError,
    NoScenesError,
    TileNotFoundError,
)
from .naip import naip_tile_urls, search_naip
from .sentinel import (
    BAND_ALIASES,
    BAND_PRESETS,
    BAND_RESOLUTION,
    band_url,
    clearest_scene,
    download_sentinel2,
    scene_summary,
    search_sentinel2,
)
from .usgs import DEM_DATASETS, dem_tile_urls, download_dem, search_dem

__version__ = "0.5.1"

#: Lazily-imported names that need the raster/xarray extras
_LAZY = {
    "clip_reproject": "raster",
    "make_grid": "raster",
    "warp_into_grid": "raster",
    "write_geotiff": "raster",
    "load_dem": "load",
    "load_sentinel2": "load",
    "stack": "load",
    "composite": "_composite",
    "terrain": "_terrain",
    "slope_aspect": "_terrain",
    "hillshade": "_terrain",
    "ndvi": "indices",
    "ndwi": "indices",
    "nbr": "indices",
    "evi": "indices",
    "savi": "indices",
    "normalized_difference": "indices",
    "elevation": "load",
    "show": "export",
    "ndmi": "indices",
    "ndsi": "indices",
    "ndre": "indices",
    "ndbi": "indices",
    "gndvi": "indices",
    "msavi": "indices",
    "bsi": "indices",
    "INDICES": "indices",
    "load_naip": "naip",
    "time_series": "timeseries",
    "to_geotiff": "export",
    "to_cog": "export",
    "preview": "export",
    "to_rioxarray": "interop",
    "reproject": "interop",
    "sample": "zonal",
    "zonal_stats": "zonal",
}

#: which optional extra to point users at when a lazy submodule can't be
#: imported (its heavy deps are missing on a core-only install)
_EXTRA_FOR_MODULE = {
    "raster": "raster",
    "export": "raster",
    "zonal": "raster",
    "load": "xarray",
    "_composite": "xarray",
    "_terrain": "xarray",
    "timeseries": "xarray",
    "indices": "xarray",
    "naip": "xarray",
    "interop": "interop",
}


def __getattr__(name):
    if name in _LAZY:
        import importlib

        modname = _LAZY[name]
        try:
            mod = importlib.import_module(f".{modname}", __name__)
        except MissingDependencyError:
            raise  # the submodule already produced a helpful message
        except ImportError as exc:
            extra = _EXTRA_FOR_MODULE.get(modname, "all")
            raise MissingDependencyError(
                f"{name!r} needs the optional {extra!r} dependencies; "
                f"install with: pip install 'earthfetch[{extra}]'"
            ) from exc
        obj = getattr(mod, name)
        # cache the resolved object so later accesses skip the import.
        # submodules are underscore-prefixed (_composite, _terrain) so a
        # user's ``import earthfetch.<name>`` can never shadow these
        # functions in the package namespace.
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
    "composite", "terrain", "time_series", "elevation",
    "load_naip", "search_naip", "naip_tile_urls",
    "ndvi", "ndwi", "nbr", "evi", "savi",
    "ndmi", "ndsi", "ndre", "ndbi", "gndvi", "msavi", "bsi",
    "normalized_difference",
    "to_geotiff", "to_cog", "preview", "show",
    # interop & analysis (extras)
    "to_rioxarray", "reproject", "sample", "zonal_stats",
    # aoi
    "AOI", "resolve_aoi", "geocode", "utm_crs",
    # metadata
    "DEM_DATASETS", "BAND_ALIASES", "BAND_RESOLUTION", "BAND_PRESETS",
    # exceptions
    "EarthfetchError", "DownloadError", "TileNotFoundError",
    "NoScenesError", "BandNotFoundError", "MissingDependencyError",
]
