# Changelog

## 0.6.0 (2026-07-06)

### Changed
- **Reflectance is now the Sentinel-2 default across the entire array API.**
  `load_sentinel2` and `stack` scale DNs to surface reflectance (0..1) by
  default, matching `composite`/`time_series` — so an index like `ndvi`
  behaves identically no matter which loader produced the data. Pass
  `scale=False` for raw DNs.
  **Breaking:** `load_sentinel2` and `stack` previously returned raw DNs.

## 0.5.1 (2026-07-06)

### Fixed
- On a core-only install, calling an analysis function (e.g. `composite`,
  `time_series`, `sample`) raised a raw `ModuleNotFoundError: No module
  named 'numpy'`. The lazy loader now catches the missing heavy dependency
  and raises a `MissingDependencyError` naming the extra to install
  (`pip install 'earthfetch[xarray]'`).

## 0.5.0 (2026-07-06)

### Added
- **`time_series`**: cloud-masked Sentinel-2 datacubes — one time step per
  clear acquisition day, `(time, band, y, x)`, with optional `freq`
  resampling (e.g. monthly medians) for change detection and phenology.
- **`sample`** and **`zonal_stats`**: read raster values at points, or
  aggregate over polygons (mean NDVI per field, elevation stats per
  watershed) — for any earthfetch DataArray/Dataset.
- **rioxarray interop** (`to_rioxarray`, `reproject`) under a new
  `interop` extra: attach the earthfetch CRS/transform so the `.rio`
  accessor works and results drop into existing rioxarray workflows.
- **`elevation(points)`**: meters at a point (or array of points) — the
  most direct DEM lookup.
- **`show(obj)`**: render a result inline with matplotlib (RGB stretch or
  colormapped single band) under a new `plot` extra.
- **Named band presets**: pass `bands="true_color"`, `"false_color"`,
  `"agriculture"`, ... to `composite`/`time_series`/`load_sentinel2`
  instead of ESA ids (see `BAND_PRESETS`). Also fixes a single band id
  string (`bands="B08"`) being split into characters.
- **`normalized_difference(obj, a, b)`**: generic index for any two bands.
- Seven spectral indices: `ndmi`, `ndsi`, `ndre`, `ndbi`, `gndvi`,
  `msavi`, `bsi` (twelve total).
- `py.typed` marker so type hints are visible to mypy/pyright.
- Ruff lint job in CI; version is now single-sourced from `__init__.py`.

### Fixed
- **`terrain`/`composite` became uncallable after importing the
  submodule** (`import earthfetch.terrain` shadowed the function with the
  module, so `ef.terrain(...)` raised "module object is not callable").
  The implementation modules are now `_terrain`/`_composite`.
- **Point and axis-aligned-line AOIs crashed** in `validate_bbox`
  (zero-area bounds). Degenerate geometries are padded to a small valid
  bbox, so a shapely `Point` resolves like any other AOI.
- **Exporting/previewing a single selected band** (`da.sel(band=...)`)
  crashed on the 0-d `band` coordinate.

## 0.4.0 (2026-07-02)

### Added
- **NAIP aerial imagery** (0.6-1 m, US) via Microsoft Planetary Computer:
  `load_naip(aoi)` / `search_naip()`. Anonymous SAS tokens fetched and
  cached automatically — still zero keys. Newest acquisition per quad.

### Fixed
- **Fragment bug**: geocoded place names clipped output to the place's
  boundary polygon, returning what looked like a torn fragment. Geocoded
  AOIs now return the full rectangle; pass `clip=True` to cut to the
  boundary. Explicit polygon AOIs still clip by default.
- **Windowed reads now use COG overviews**: reads are decimated to ~2x
  the target resolution. NAIP mosaics that previously timed out (>10 min
  reading 0.6 m pixels for a 30 m grid) now finish in seconds.

## 0.3.0 (2026-07-02)

### Added
- **Any-AOI input** everywhere: bbox, GeoJSON dict/file, shapely geometry
  (`__geo_interface__`), or place name (free Nominatim geocoding).
  Polygon AOIs clip results automatically.
- **`composite()`** — cloud-free multi-scene composites: SCL cloud
  masking, seamless across MGRS tile boundaries, median/mean/first,
  reflectance-scaled via STAC metadata.
- **Spectral indices**: `ndvi`, `ndwi`, `nbr`, `evi`, `savi` on any
  earthfetch Dataset/DataArray.
- **`terrain()`** — slope, aspect, hillshade from any DEM source.
- **Export**: `to_geotiff()`, `to_cog()`, `preview()` (stretched PNG).
- `crs="utm"` shorthand auto-selects the AOI's UTM zone (new default in
  `composite`/`terrain`).

## 0.2.0 (2026-07-02)

### Added
- `load_dem`, `load_sentinel2`, `stack` — bbox in, aligned `xarray` out.
  Windowed HTTP-range reads from COGs: only the bbox window is transferred.
- Copernicus GLO-30 global DEM source (`source="copernicus"`, auto
  fallback outside the US).
- Shared session with retry/backoff; parallel tile/band downloads.
- Typed exceptions (`TileNotFoundError`, `NoScenesError`, ...).
- Default cache dir (`$EARTHFETCH_CACHE` override); Content-Length
  verification on downloads.
- CLI: `--json` search output, `--verbose` logging.
- `py.typed`, mocked-HTTP test suite, CI workflow.

### Changed
- Library is silent: no prints, `logging` + optional progress callbacks.
- `download_*` default `out_dir` is now the cache dir, not the cwd.

## 0.1.0 (2026-07-01)

Initial release: USGS 3DEP DEM + Sentinel-2 L2A search/download, CLI.
