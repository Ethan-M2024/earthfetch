# Time series & analysis

## Time-series datacubes

Where [`composite`](api.md) collapses a date range to one cloud-free image,
`time_series` keeps every clear acquisition as its own time step — the
`(time, band, y, x)` datacube for change detection and phenology.

```python
import earthfetch as ef

cube = ef.time_series("Central Valley, California",
                      bands=["B08", "B04"],
                      start="2026-03-01", end="2026-09-01")
cube.dims          # ('time', 'band', 'y', 'x')

ndvi = ef.ndvi(cube)          # indices work over the whole cube
ndvi_monthly = ef.time_series("Central Valley, California",
                              bands=["B08", "B04"],
                              start="2026-03-01", end="2026-09-01",
                              freq="MS")   # monthly median composites
```

## Sampling points

Read pixel values at coordinates — elevation at stations, band values at
field plots. Points outside the raster come back as NaN.

```python
dem = ef.load_dem((-111.9, 40.7, -111.8, 40.8), crs="utm")
elevations = ef.sample(dem, [(-111.85, 40.75), (-111.88, 40.72)])

rgb = ef.composite("Moab, Utah", start="2026-05-01", end="2026-06-15")
values = ef.sample(rgb, (-109.55, 38.57))   # (n_bands,) at one point
```

## Zonal statistics

Aggregate over polygons — mean NDVI per field, elevation stats per
watershed. Returns one dict per polygon (per-band for banded inputs).

```python
ndvi = ef.ndvi(ef.composite("fields.geojson",
                            bands=["B08", "B04"],
                            start="2026-06-01", end="2026-07-01"))
ndvi.attrs = ...  # carry crs/transform from the composite if needed

stats = ef.zonal_stats(ndvi, "fields.geojson",
                       stats=("mean", "min", "max", "std", "count"))
# [{'mean': 0.72, 'min': 0.31, 'max': 0.89, 'std': 0.11, 'count': 4210}, ...]
```

## rioxarray interop

earthfetch arrays carry their CRS/transform in `.attrs`. `to_rioxarray`
attaches them as a first-class georeference so the whole `.rio` accessor
works, dropping results straight into existing rioxarray workflows.

```python
da = ef.to_rioxarray(ef.composite("Moab, Utah", start="2026-05-01",
                                  end="2026-06-15"))
da.rio.to_raster("moab.tif")
wgs84 = ef.reproject(da, "EPSG:4326")     # or da.rio.reproject(...)
```
