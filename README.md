# earthfetch

**Analysis-ready Earth data in one line. Zero API keys. Zero accounts.**

📖 **Docs: https://ethan-m2024.github.io/earthfetch/**

```python
import earthfetch as ef

# Cloud-free composite of any place on Earth — geocoded, cloud-masked,
# mosaicked across scene boundaries, reflectance-scaled, in your UTM zone:
rgb = ef.composite("Moab, Utah", bands=["B04", "B03", "B02"],
                   start="2026-05-01", end="2026-06-15")
ef.preview(rgb, "moab.png")

# NDVI for a farm polygon, clipped to its boundary:
ds = ef.composite("field.geojson", bands=["B08", "B04"],
                  start="2026-05-01", end="2026-06-01")
ndvi = ef.ndvi(ds)

# Terrain anywhere (Alps -> Copernicus DEM, auto-UTM):
terr = ef.terrain((6.85, 45.82, 6.90, 45.87))   # dem, slope, aspect, hillshade
ef.to_cog(terr.hillshade, "hillshade.tif")

# Floodplain map: height above the river, river found automatically:
r = ef.rem((-110.72, 45.38, -110.62, 45.46), resolution="1m")
ef.preview(r.rem, "rem.png", cmap="YlGnBu_r", vmin=0, vmax=10, shade=r.hillshade,
           legend=True)   # colorbar: "Height above river (m)"

# Radar sees through clouds: Sentinel-1 backscatter and a water mask
s1 = ef.load_sentinel1("Sacramento, CA", start="2026-01-01", end="2026-01-20")
water = ef.water_mask(s1)
```

One scene replaces an afternoon: no EarthExplorer queues, no Copernicus
tokens, no manual SCL masking, no tile mosaicking, no gdalwarp.
Only the AOI window travels over the network — everything is read from
Cloud-Optimized GeoTIFFs with HTTP range requests.

## AOI: pass anything

Every function takes bboxes, GeoJSON dicts, `.geojson` files, shapely
geometries, or place names:

```python
ef.composite((-111.9, 40.7, -111.8, 40.8), ...)   # bbox tuple
ef.composite("Yosemite National Park", ...)        # geocoded (Nominatim)
ef.composite("watershed.geojson", ...)             # file; clips to polygon
ef.composite(shapely_polygon, ...)                 # __geo_interface__
```

`crs="utm"` (default in `composite`/`terrain`/`load_naip`) picks the right
UTM zone. Explicit polygons clip results to their boundary; geocoded place
names return the full rectangle (pass `clip=True` to cut to the boundary).

## Data sources (all free, no auth)

| Source | What | Coverage | Resolutions |
|---|---|---|---|
| USGS 3DEP (The National Map) | DEM | United States | 1 m, 10 m, 30 m, 5 m (AK) |
| Copernicus GLO-30 (AWS) | DEM | Global | 30 m |
| Sentinel-2 L2A (Earth Search / AWS) | Multispectral imagery | Global | 10 / 20 / 60 m |
| NAIP (Planetary Computer) | Aerial photography (RGBN) | United States | 0.6-1 m |
| Landsat 8/9 C2 L2 (Planetary Computer) | Multispectral imagery | Global | 30 m |
| Sentinel-1 RTC (Planetary Computer) | Radar backscatter (VV/VH) | Global | 10 m |
| ArcticDEM v4.1 (PGC / AWS) | DEM | Arctic (~60°N and up) | 2 m, 10 m, 32 m |
| REMA v2 (PGC / AWS) | DEM | Antarctica | 2 m, 10 m, 32 m |
| USGS NHD / OpenStreetMap | River centerlines | US / global | vector |

Looking for "Google Earth"-quality imagery? That's NAIP: actual aerial
photos where you can see individual cars and trees.

```python
img = ef.load_naip("Moab, Utah", res=1)          # 1 m RGB mosaic
nir = ef.load_naip(aoi, bands=["N","R","G"])     # false-color infrared
```

## Install

```bash
pip install earthfetch              # search + download only (requests)
pip install "earthfetch[xarray]"    # + load_dem / load_sentinel2 / stack
```

## Relative Elevation Models

A REM flattens a valley so the river sits at zero and every terrace, old
channel, and flood-prone swale shows as height above the water. `ef.rem`
runs the whole workflow: DEM download, river centerline (USGS NHD in the
US, OpenStreetMap elsewhere), water-surface sampling, inverse-distance
interpolation, subtraction.

![REM of the Yellowstone River near Livingston, Montana, from 1 m USGS lidar](https://raw.githubusercontent.com/Ethan-M2024/earthfetch/main/docs/img/rem_yellowstone.png)

```python
r = ef.rem("valley.geojson", resolution="1m")     # rem, dem, water_surface, hillshade
r = ef.rem(bbox, river="Snake")                   # pick a river by name
r = ef.rem(bbox, river="my_centerline.shp")       # or bring your own line
ef.to_cog(r.rem, "rem.tif")

line = ef.river_centerline(bbox)                  # just the river, as GeoJSON
```

```bash
earthfetch rem --bbox -110.72 45.38 -110.62 45.46 --resolution 1m --png rem.png
```

Draw the AOI around a valley segment with the river running through it; a
few km of river works best.

## Radar: Sentinel-1

Radar works through cloud and at night: floods under storm cover, sea ice,
winter landscapes. Gamma naught backscatter, already terrain corrected.

```python
s1 = ef.load_sentinel1(aoi, start="2026-08-01", end="2026-09-20")      # newest pass, dB
s1 = ef.load_sentinel1(aoi, start=..., end=..., method="median")      # speckle-free
s1 = ef.load_sentinel1(aoi, start=..., end=..., orbit_state="ascending")
water = ef.water_mask(s1, threshold=-18)                              # 1 = open water
```

## Polar DEMs: ArcticDEM and REMA

```python
dem = ef.load_dem("Fairbanks, Alaska", resolution="2m", crs="utm", source="arcticdem")
dem = ef.load_dem(bbox, resolution="10m", source="polar")   # Arctic or Antarctic by hemisphere
terr = ef.terrain(bbox, resolution="2m", source="arcticdem")
```

Polar heights are relative to the WGS84 ellipsoid, not a geoid, so they can
differ from USGS/Copernicus by tens of meters.

## Composites, indices, terrain

```python
# method: "median" (robust), "mean", "first" (fastest)
da = ef.composite(aoi, bands=["B04","B03","B02"], start=..., end=...,
                  method="median", mask_clouds=True, max_scenes=8)

ef.ndvi(ds); ef.ndwi(ds); ef.nbr(ds); ef.evi(ds); ef.savi(ds)

terr = ef.terrain(aoi, products=["dem","slope","aspect","hillshade"],
                  resolution="10m")   # USGS in US, Copernicus elsewhere

ef.to_geotiff(obj, "out.tif"); ef.to_cog(obj, "out.tif")
ef.preview(obj, "look.png")           # percentile-stretched quicklook
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
