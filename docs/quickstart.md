# Quickstart

Every example runs against live, free, no-auth APIs.

## A cloud-free RGB composite

```python
import earthfetch as ef

rgb = ef.composite("Zion National Park",
                   bands=["B04", "B03", "B02"],
                   start="2026-05-01", end="2026-06-15")
ef.preview(rgb, "zion.png")     # percentile-stretched quick-look PNG
ef.to_cog(rgb, "zion.tif")      # Cloud-Optimized GeoTIFF, reflectance
```

`composite` searches every Sentinel-2 scene touching the AOI, keeps the
clearest acquisition days (all MGRS tiles per day, so seams disappear),
masks cloud/shadow pixels with the SCL band, and reduces per pixel.

## A vegetation index

```python
ds = ef.composite((-111.9, 40.7, -111.8, 40.8),
                  bands=["B08", "B04"],
                  start="2026-06-01", end="2026-07-01")
ndvi = ef.ndvi(ds)
ndvi.attrs = ds.attrs           # carry CRS/transform onto the index
ef.to_geotiff(ndvi, "ndvi.tif")
```

Twelve indices ship built in: `ndvi`, `ndwi`, `nbr`, `evi`, `savi`, `ndmi`,
`ndsi`, `ndre`, `ndbi`, `gndvi`, `msavi`, `bsi`.

## Terrain

```python
terr = ef.terrain("Mount Rainier")   # dem, slope, aspect, hillshade
ef.to_cog(terr.hillshade, "rainier_hillshade.tif")
```

Inside the US you get USGS 3DEP; elsewhere it falls back to Copernicus
GLO-30 automatically. Gradients are computed in the AOI's UTM zone so
slope and aspect are metric.

## Just the files

If you only want GeoTIFFs on disk (no rasterio/xarray needed):

```python
paths = ef.download_dem((-112, 40, -111, 41), resolution="10m")
scene = ef.clearest_scene((-112, 40, -111, 41), "2026-05-01", "2026-06-01")
files = ef.download_sentinel2(scene, bands=["B04", "B08", "TCI"])
```

## From the command line

```bash
earthfetch dem --bbox -112 40 -111 41 --resolution 10m --out dem/
earthfetch s2  --bbox -112 40 -111 41 --start 2026-05-01 --end 2026-06-01 \
               --bands B04,B03,B02 --out imagery/
```
