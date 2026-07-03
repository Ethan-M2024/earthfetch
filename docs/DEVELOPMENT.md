# earthfetch — Development History

How this library went from idea to a four-source, zero-key geospatial
data toolkit, over 2026-07-01 → 2026-07-02. Written as a record of what
was built, why each decision was made, what broke, and how it was fixed.

---

## The idea

**Goal:** a pip-installable Python library that pulls DEM and satellite
imagery without the usual pain — no EarthExplorer queues, no Copernicus
tokens, no Earthdata logins, no API keys of any kind.

**Positioning:** "`requests` for Earth data. Any AOI in, analysis-ready
arrays out. No keys, no accounts, no GDAL wrestling."

The moat is zero-configuration. Every data source chosen is public,
free, and anonymous. Competing tools (`stackstac`, `earthaccess`,
Google Earth Engine wrappers) all require auth ceremonies or glue code
across five libraries.

---

## Version history

### v0.1.0 — Core search + download (2026-07-01)

The minimum viable library: find and download files.

- **USGS 3DEP DEMs** via The National Map API (`usgs.py`):
  1 m, 1/3 arc-second (~10 m), 1 arc-second (~30 m), Alaska 5 m.
- **Sentinel-2 L2A** via the Earth Search STAC API on AWS
  (`sentinel.py`): global 10/20/60 m multispectral COGs, searched by
  bbox/date/cloud-cover, sorted clearest-first.
- ESA band ids (`B04`) and Earth Search asset keys (`red`) both accepted.
- Streaming downloads with `.part` files renamed on completion —
  interrupted transfers never leave corrupt output; re-runs skip
  finished files.
- `clip_reproject()`: merge tiles, clip to bbox, reproject to any CRS
  (optional `rasterio` extra).
- CLI: `earthfetch dem ...` / `earthfetch s2 ...`.
- Interactive demo (`examples/interactive_fetch.py`): pick any bbox,
  any CRS, any resolution.

**Verified live:** Salt Lake City bbox → DEM elevations 1289–1397 m
(correct for the valley), Sentinel-2 scenes at 0.5 % cloud.

**Fix along the way:** argparse rejects `--bbox -111.9,40.7,...`
(leading minus parsed as a flag) → switched to `--bbox MIN_LON MIN_LAT
MAX_LON MAX_LAT` with `nargs=4`.

### v0.2.0 — Pipeline-grade rework (2026-07-02)

Ten changes to make it a real library rather than a script collection:

1. **Windowed COG reads** (`raster.py: warp_into_grid`). Every source
   is a Cloud-Optimized GeoTIFF; rasterio reads just the AOI window via
   HTTP range requests. 400 MB tile downloads became ~2 MB window reads.
2. **Array API** (`load.py`): `load_dem()` / `load_sentinel2()` return
   `xarray.DataArray` — float32, NaN nodata, CRS/transform/source URLs
   in `attrs`. No files touch disk.
3. **`stack()`**: DEM + any Sentinel-2 bands warped onto one
   pixel-aligned grid; returns an ML-ready `xarray.Dataset`.
4. **Silent library**: all `print()` removed; `logging` on the
   `earthfetch` logger plus an optional progress callback
   (`utils.print_progress` for scripts/CLI).
5. **Reliability**: shared `requests.Session` with 4-retry backoff,
   parallel downloads (thread pool), Content-Length verification,
   typed exceptions (`TileNotFoundError`, `NoScenesError`,
   `DownloadError`, `BandNotFoundError`, `MissingDependencyError`).
6. **Copernicus GLO-30 global DEM** (`copernicus.py`): 30 m worldwide
   on AWS Open Data; `source="auto"` falls back to it outside the US.
   Verified on Mont Blanc (max elevation > 4000 m).
7. **Cache dir**: platform-appropriate default, `$EARTHFETCH_CACHE`
   override.
8. **Packaging hygiene**: `py.typed`, mocked-HTTP tests (`responses`)
   so CI needs no network, GitHub Actions matrix (3.9/3.11/3.13) +
   PyPI trusted-publishing job on tag push, CHANGELOG.
9. **CLI**: `--json` machine-readable search output, `-v` logging.
10. **Provenance**: source URLs + earthfetch version written into
    GeoTIFF tags.

**Benchmark:** `stack()` returning aligned DEM + B04 + B08 took
**6.5 s**; the v0.1.0 equivalent downloaded 250+ MB over minutes.

**Fix:** truncated downloads surfaced as raw
`requests.ChunkedEncodingError` — wrapped into `DownloadError` with
`.part` cleanup.

### v0.3.0 — Tier 1: what converts professionals (2026-07-02)

Brainstormed what actually wastes geospatial pros' time, ranked it,
built the top tier:

- **Any-AOI input** (`aoi.py`): every function accepts a bbox tuple,
  GeoJSON dict (geometry/Feature/FeatureCollection), a `.geojson`
  file path, any object with `__geo_interface__` (shapely,
  geopandas), or a **place name** geocoded via OpenStreetMap
  Nominatim. Polygon AOIs clip the output to their boundary.
- **`composite()`** (`composite.py`) — the headline feature. One call:
  searches all scenes in a date range, groups them by acquisition day
  (so MGRS tile seams disappear — every tile of a satellite pass is
  kept together), ranks days by cloud cover, keeps the clearest N,
  masks invalid pixels using the SCL layer (classes 0, 1, 3, 8, 9, 10:
  nodata, saturated, shadow, clouds, cirrus), converts DNs to surface
  reflectance using per-asset STAC `raster:bands` scale/offset
  (correctly handling ESA's 2022 processing-baseline offset change),
  and reduces per pixel by median/mean/first.
- **Spectral indices** (`indices.py`): `ndvi`, `ndwi`, `nbr`, `evi`,
  `savi` — work on Datasets and band-dimension DataArrays.
- **`terrain()`** (`terrain.py`): slope, aspect, hillshade from any
  DEM source, computed with metric-safe gradients (default CRS is the
  AOI's UTM zone).
- **Export** (`export.py`): `to_geotiff()`, `to_cog()`, and
  `preview()` (percentile-stretched PNG quicklook).
- **`crs="utm"`** shorthand auto-selects the UTM zone from the AOI
  center; default for `composite`/`terrain`.

**Verified live:**
- `composite("Moab, Utah", ...)` — geocoded, 16 scenes over 8 clear
  days, 24 s, real red-rock true-color image.
- NDVI on a cloud-masked composite: 100 % finite pixels (no cloud
  holes), mean 0.625 over a green valley.
- Alps terrain: auto-picked EPSG:32632, max elevation 4808 m — exactly
  Mont Blanc.
- Triangle polygon clip: 49 % finite pixels (expected ~50 %).

**Bug found while testing:** lazy-import name collision. Importing the
`composite` *submodule* set it as a package attribute, shadowing the
`composite()` *function* on the second access (`'module' object is not
callable`). Fixed by caching the resolved function in package globals
inside `__getattr__`.

### v0.4.0 — NAIP aerial + two real bug fixes (2026-07-02)

User request: "add Google Earth as an imagery option." Google Earth
imagery is licensed/commercial (no legal API without keys and ToS
violations), so the equivalent that is legal, free, and keyless:

- **NAIP aerial photography** (`naip.py`): 0.6–1 m RGBN photos of the
  US via Microsoft Planetary Computer. Access needs SAS tokens, but
  they're issued **anonymously** — fetched and cached automatically,
  so the zero-key promise holds. `load_naip(aoi)` mosaics the newest
  acquisition per quad; `year=` pins a survey year;
  `bands=["N","R","G"]` gives false-color infrared.

- **Fix 1 — the "fragment" bug (user-reported):** geocoded place names
  carried the place's boundary polygon, and output was clipped to it —
  a Moab request returned only pixels inside the city limits, looking
  like a torn fragment. Resolution: `AOI` gained `clip_default`;
  explicit polygons (files, shapely, GeoJSON) still clip, geocoded
  names return the full rectangle, and `clip=True/False` overrides
  either way. Verified: place-name composite went from ~30 % to 100 %
  finite pixels.

- **Fix 2 — reads ignored COG overviews:** `warp_into_grid` read
  windows at full native resolution regardless of the target grid.
  For NAIP that meant pulling 0.6 m pixels to build a 30 m mosaic —
  ~2500× the necessary data; the first NAIP test ran past a 10-minute
  timeout. Fixed by decimating reads to ~2× the target resolution
  (`out_shape` on `ds.read`, with the window transform rescaled), which
  GDAL serves from overview levels. The same fix speeds up every
  coarse-resolution Sentinel-2 and DEM read.

**Verified live:** full Moab NAIP mosaic at 2 m — 3760×2861 px, 4 quads,
seamless, 100 % finite, individual buildings visible. 128 s for that
10-megapixel request; a 30 m composite of the same area: 9 s.

---

## Architecture

```
aoi.py         bbox/GeoJSON/shapely/place-name -> AOI(bbox, geometry, clip_default)
usgs.py        The National Map API -> 3DEP DEM tile URLs (US)
copernicus.py  tile-name math + HEAD checks -> GLO-30 DEM URLs (global)
sentinel.py    Earth Search STAC -> scenes, band URLs, reflectance scale/offset
naip.py        Planetary Computer STAC + anonymous SAS -> aerial quad URLs (US)
raster.py      the engine: windowed/decimated COG reads -> target grid mosaics
load.py        load_dem / load_sentinel2 / stack -> xarray
composite.py   day-grouped, SCL-masked, median composites -> xarray
terrain.py     slope / aspect / hillshade from any DEM
indices.py     ndvi / ndwi / nbr / evi / savi
export.py      to_geotiff / to_cog / preview PNG
utils.py       retry session, cache dir, verified streaming downloads
exceptions.py  EarthfetchError hierarchy
cli.py         earthfetch dem / earthfetch s2 (+ --json, -v)
```

Data flow for the headline call:

```
ef.composite("Moab, Utah", bands=[...], start=..., end=...)
   └─ aoi.py       geocode -> bbox (+ boundary polygon, unused unless clip=True)
   └─ sentinel.py  STAC search -> scenes -> clearest acquisition days
   └─ raster.py    make_grid (auto-UTM) -> per band, per scene:
                   HTTP-range read of just the AOI window, decimated to
                   ~2x target res, reprojected into the grid
   └─ composite.py SCL mask -> reflectance scale -> nanmedian
   └─ xarray out   float32, NaN nodata, scene ids/dates in attrs
```

Design rules that held throughout:

- **Zero keys, zero accounts** — every source is anonymous.
- **Only the AOI travels the network** — range requests into COGs,
  never whole files (after v0.4.0, at the right overview level too).
- **The library is silent** — logging only; printing is for the CLI
  and examples.
- **Base install stays light** — `requests` only; rasterio/xarray are
  extras (`earthfetch[raster]`, `earthfetch[xarray]`); heavy imports
  are lazy via package `__getattr__`.
- **Everything raises `EarthfetchError` subclasses** with actionable
  messages ("USGS covers the US only — try source='copernicus'").

## Data sources

| Source | What | Coverage | Resolution | Access |
|---|---|---|---|---|
| USGS 3DEP (The National Map) | DEM | US | 1 m / 10 m / 30 m / 5 m AK | anonymous |
| Copernicus GLO-30 (AWS Open Data) | DEM | global | 30 m | anonymous |
| Sentinel-2 L2A (Earth Search, AWS) | multispectral | global | 10/20/60 m | anonymous |
| NAIP (Microsoft Planetary Computer) | aerial RGBN | US | 0.6–1 m | anonymous SAS, auto-fetched |

## Testing

- **33 offline tests** — AOI parsing, UTM zone math, index formulas,
  terrain math on synthetic ramps (45° slope / east aspect), composite
  day-grouping, export round-trips, mocked-HTTP search/pagination/
  truncation (via `responses`; a session-reset fixture makes the pool
  visible to the mock). These run in CI with no network.
- **9 live tests** (`pytest -m network`) — real API round-trips:
  USGS windowed reads, Copernicus on Mont Blanc, aligned `stack()`
  with NDVI, geocoded composite, terrain auto-UTM, NAIP full-rectangle.
- CI: GitHub Actions, Python 3.9 / 3.11 / 3.13, offline suite.
- Sanity checks were physical, not just structural: Salt Lake valley
  elevations, Mont Blanc's 4808 m summit, NDVI ~0.6 over green valley
  floor, a triangle clip covering half its bounding box.

## Repository / release state

- GitHub: https://github.com/Ethan-M2024/earthfetch (public, CI green)
- Version: 0.4.0; wheel + sdist build clean
- **Not yet on PyPI.** Remaining steps: create the PyPI account, add a
  trusted publisher (owner `Ethan-M2024`, repo `earthfetch`, workflow
  `ci.yml`, environment `pypi`), create the `pypi` environment in repo
  settings, then `git tag v0.4.0 && git push origin v0.4.0` — the
  publish job does the rest.

## Roadmap (brainstormed, not built)

- **Tier 2:** time series (`ef.timeseries(aoi, "ndvi", freq="M")`),
  Landsat (1982–present archive), ESA WorldCover landcover,
  STL/heightmap export for 3D printing and game dev.
- **Tier 3:** lazy/dask loading for state-sized AOIs, conda-forge
  packaging, a recipe-style docs site.
