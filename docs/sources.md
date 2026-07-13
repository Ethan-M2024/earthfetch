# Data sources

All sources are free and need no API key or account.

## USGS 3DEP DEMs

The National Map, United States only. Resolutions `1m`, `10m`, `30m`, and
`5m-ak` (Alaska IFSAR).

::: earthfetch.usgs.search_dem

::: earthfetch.usgs.download_dem

## Copernicus GLO-30

Global 30 m DEM on AWS Open Data. Used automatically as the fallback
outside the US.

::: earthfetch.copernicus.copernicus_dem_urls

## Sentinel-2 L2A

Multispectral imagery, global, via the Earth Search STAC API. Bands are
addressed by ESA id (`B04`, `B08`, `SCL`, `TCI`, ...).

::: earthfetch.sentinel.search_sentinel2

::: earthfetch.sentinel.clearest_scene

::: earthfetch.sentinel.covering_scenes

::: earthfetch.sentinel.download_sentinel2

## Landsat 8/9

Collection-2 Level-2 surface reflectance, global, via Microsoft Planetary
Computer (zero-key). Band labels are normalized to their Sentinel-2
equivalents (`red`→`B04`, `nir`→`B08`, ...), so the indices and band presets
work identically to Sentinel-2. Also available as `composite(...,
source="landsat")`.

::: earthfetch.landsat.search_landsat

::: earthfetch.landsat.load_landsat

## NAIP aerial imagery

0.6-1 m natural-color/near-infrared aerial photos, US only, via Microsoft
Planetary Computer. Anonymous SAS tokens are fetched automatically.

::: earthfetch.naip.search_naip
