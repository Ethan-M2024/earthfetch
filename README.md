# earthfetch

**USGS 3DEP DEMs and Sentinel-2 L2A imagery. Zero API keys. Zero accounts.**

```python
import earthfetch as ef

# DEM + red + NIR on one pixel-aligned 30 m UTM grid, in seconds:
ds = ef.stack(
    bbox=(-111.90, 40.70, -111.85, 40.75),
    crs="EPSG:32612", res=30,
    bands=["B04", "B08"],
    start="2026-05-01", end="2026-06-01",
)
ndvi = (ds.B08 - ds.B04) / (ds.B08 + ds.B04)
```

Only the bbox window travels over the network — bands and DEM tiles are Cloud-Optimized GeoTIFFs read with HTTP range requests, not full-file downloads.

## Data sources (all free, no auth)

| Source | What | Coverage | Resolutions |
|---|---|---|---|
| USGS 3DEP (The National Map) | DEM | United States | 1 m, 10 m, 30 m, 5 m (AK) |
| Copernicus GLO-30 (AWS) | DEM | Global | 30 m |
| Sentinel-2 L2A (Earth Search / AWS) | Multispectral imagery | Global | 10 / 20 / 60 m |

## Install

```bash
pip install earthfetch              # search + download only (requests)
pip install "earthfetch[xarray]"    # + load_dem / load_sentinel2 / stack
```

## Array API (pipelines)

```python
import earthfetch as ef

bbox = (-111.90, 40.70, -111.85, 40.75)  # (min_lon, min_lat, max_lon, max_lat)

# DEM as xarray.DataArray — any CRS, any pixel size
dem = ef.load_dem(bbox, resolution="10m", crs="EPSG:32612", res=10)

# Outside the US? Copernicus GLO-30 is used automatically (source="auto"),
# or ask for it explicitly:
alps = ef.load_dem((6.85, 45.82, 6.88, 45.85), crs="EPSG:32632", source="copernicus")

# Sentinel-2 bands, clearest scene in a date range
s2 = ef.load_sentinel2(bbox, bands=["B04", "B08"], crs="EPSG:32612",
                       start="2026-05-01", end="2026-06-01", max_cloud=20)

# Everything aligned on one grid (ML-ready xarray.Dataset)
ds = ef.stack(bbox, crs="EPSG:32612", res=30, bands=["B04", "B08"],
              start="2026-05-01", end="2026-06-01")
```

All arrays are float32 with NaN nodata and carry `crs`, `transform`, and source URLs in `attrs`. Bands accept ESA ids (`B02`–`B12`, `B8A`, `SCL`) or Earth Search asset keys (`red`, `nir`, ...).

## Search + download API (files)

```python
tiles = ef.search_dem(bbox, resolution="10m")           # metadata only
paths = ef.download_dem(bbox, resolution="10m", out_dir="dem")

scenes = ef.search_sentinel2(bbox, "2026-05-01", "2026-06-01", max_cloud=15)
files = ef.download_sentinel2(scenes[0], bands=["B04", "B08"], out_dir="s2")

from earthfetch import clip_reproject                    # needs [raster]
clip_reproject(paths, bbox, "EPSG:32612", "dem_utm.tif")
```

Downloads default to a per-user cache (`$EARTHFETCH_CACHE` to override), stream to `.part` files, verify byte counts, skip files already on disk, and run in parallel. The library never prints — it logs to the `earthfetch` logger; pass `progress=earthfetch.utils.print_progress` for a progress bar in scripts.

## CLI

```bash
earthfetch dem --bbox -111.9 40.7 -111.8 40.8 --search-only --json
earthfetch dem --bbox -111.9 40.7 -111.8 40.8 --resolution 10m --out dem/
earthfetch s2  --bbox -111.9 40.7 -111.8 40.8 \
    --start 2026-05-01 --end 2026-06-01 --bands B04,B08 --out s2/
```

`--json` emits machine-readable search results; `-v` logs library activity.

## Errors

Everything raises a subclass of `earthfetch.EarthfetchError`:
`TileNotFoundError` (bbox outside coverage), `NoScenesError` (no clear
scenes — widen dates or raise `max_cloud`), `DownloadError`,
`BandNotFoundError`, `MissingDependencyError`.

## License

MIT
