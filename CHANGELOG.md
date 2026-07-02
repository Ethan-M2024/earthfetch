# Changelog

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
