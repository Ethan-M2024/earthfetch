# API reference

## Array API

One call, bbox in, aligned `xarray` out. Requires `earthfetch[xarray]`.

::: earthfetch.load.load_dem

::: earthfetch.load.load_sentinel2

::: earthfetch.load.stack

::: earthfetch._composite.composite

::: earthfetch._terrain.terrain

::: earthfetch.naip.load_naip

::: earthfetch.timeseries.time_series

::: earthfetch.load.elevation

## Analysis

Extract values from any earthfetch raster at points or over polygons.
Requires the `raster` extra.

::: earthfetch.zonal.sample

::: earthfetch.zonal.zonal_stats

## Interoperability

Bridge earthfetch results into the rioxarray / rasterio ecosystem.
Requires the `interop` extra (`pip install earthfetch[interop]`).

::: earthfetch.interop.to_rioxarray

::: earthfetch.interop.reproject

## Spectral indices

Each accepts an `xarray.Dataset` (band-named variables) or a `DataArray`
with a `band` coordinate, and returns a named `DataArray`.

::: earthfetch.indices.normalized_difference

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

::: earthfetch.export.show

## Raster operations

::: earthfetch.raster.clip_reproject

## Exceptions

::: earthfetch.exceptions.EarthfetchError

::: earthfetch.exceptions.TileNotFoundError

::: earthfetch.exceptions.NoScenesError

::: earthfetch.exceptions.BandNotFoundError

::: earthfetch.exceptions.DownloadError

::: earthfetch.exceptions.MissingDependencyError
