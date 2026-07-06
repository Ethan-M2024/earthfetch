# earthfetch

**Analysis-ready Earth data in one line. Zero API keys. Zero accounts.**

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
```

One scene replaces an afternoon: no EarthExplorer queues, no Copernicus
tokens, no manual SCL masking, no tile mosaicking, no gdalwarp. Only the AOI
window travels over the network — everything is read from Cloud-Optimized
GeoTIFFs with HTTP range requests.

## Install

```bash
pip install earthfetch          # search + download (requests only)
pip install "earthfetch[raster]"  # + windowed COG reads, clip/reproject
pip install "earthfetch[xarray]"  # + one-call array API (load_*, composite, terrain)
```

## Data sources (all free, no auth)

| Source | What | Coverage | Resolutions |
|---|---|---|---|
| USGS 3DEP (The National Map) | DEM | United States | 1 m, 10 m, 30 m, 5 m (AK) |
| Copernicus GLO-30 (AWS) | DEM | Global | 30 m |
| Sentinel-2 L2A (Earth Search / AWS) | Multispectral imagery | Global | 10 / 20 / 60 m |
| NAIP (Planetary Computer) | Aerial photography (RGBN) | United States | 0.6-1 m |

Next: the [Quickstart](quickstart.md), or jump to the [API reference](api.md).
