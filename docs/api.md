# API reference

## Array API

One call, bbox in, aligned `xarray` out. Requires `earthfetch[xarray]`.

::: earthfetch.load.load_dem

::: earthfetch.load.load_sentinel2

::: earthfetch.load.stack

::: earthfetch._composite.composite

::: earthfetch._terrain.terrain

::: earthfetch.naip.load_naip

## Spectral indices

Each accepts an `xarray.Dataset` (band-named variables) or a `DataArray`
with a `band` coordinate, and returns a named `DataArray`.

::: earthfetch.indices.ndvi

::: earthfetch.indices.ndwi

::: earthfetch.indices.nbr

::: earthfetch.indices.evi

::: earthfetch.indices.savi

::: earthfetch.indices.ndmi

::: earthfetch.indices.ndsi

::: earthfetch.indices.ndre

::: earthfetch.indices.ndbi

::: earthfetch.indices.gndvi

::: earthfetch.indices.msavi

::: earthfetch.indices.bsi

## Export

Requires `earthfetch[raster]`.

::: earthfetch.export.to_geotiff

::: earthfetch.export.to_cog

::: earthfetch.export.preview

## Raster operations

::: earthfetch.raster.clip_reproject

## Exceptions

::: earthfetch.exceptions.EarthfetchError

::: earthfetch.exceptions.TileNotFoundError

::: earthfetch.exceptions.NoScenesError

::: earthfetch.exceptions.BandNotFoundError

::: earthfetch.exceptions.DownloadError

::: earthfetch.exceptions.MissingDependencyError
