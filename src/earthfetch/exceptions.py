"""earthfetch exception hierarchy. Catch ``EarthfetchError`` for everything."""


class EarthfetchError(Exception):
    """Base class for all earthfetch errors."""


class DownloadError(EarthfetchError):
    """A download failed or arrived truncated."""


class TileNotFoundError(EarthfetchError):
    """No DEM tiles cover the requested bbox."""


class NoScenesError(EarthfetchError):
    """No Sentinel-2 scenes match the search."""


class BandNotFoundError(EarthfetchError):
    """Requested band/asset is not present in the scene."""


class MissingDependencyError(EarthfetchError, ImportError):
    """An optional dependency (rasterio, xarray) is required but missing."""
