# Performance & benchmarks

earthfetch reads only the window you ask for. Every array function issues
HTTP range requests against Cloud-Optimized GeoTIFFs, so the bytes over the
wire scale with your area of interest — not with the size of the source
file.

## Indicative timings

Measured on small AOIs from a laptop over home broadband with a cold cache
(`python scripts/benchmark.py`). Numbers are network-dependent and meant to
show the *shape* of typical operations, not to be precise.

| Operation | Time | Detail |
|---|---|---|
| `load_dem` (10 m, ~2 km AOI) | ~3 s | 172×224 px, windowed read of a **383 MB** tile — no full download |
| `elevation` (1 point) | ~0.5 s | loads + samples a DEM |
| `load_sentinel2` (3 bands, ~4 km) | ~2 s | 356×450 px, single clearest scene |
| `composite` (true color, ~4 km) | ~14 s | 8 acquisition days blended + SCL cloud-masking |

## Why the windowed read matters

The DEM row is the whole pitch in one line: a naïve workflow downloads the
383 MB source tile and then clips it; earthfetch transfers only the ~40 KB
window and returns an array in about 3 seconds. The savings grow with the
source file — 1 m DEM tiles and 0.6 m NAIP quads are gigabytes.

`composite` is the slowest operation because it is doing the most: it
searches every scene touching the AOI, reads the SCL band plus each
requested band for the clearest ~8 days, masks clouds, and reduces per
pixel. Cost scales with `max_scenes`, the number of `bands`, and AOI size.

## Tuning

- **Fewer scenes** — lower `max_scenes` (default 8) for faster, less robust
  composites; `method="first"` stops as soon as every pixel is filled.
- **Coarser resolution** — pass a larger `res`; reads come from COG
  overviews, so a 30 m composite over a wide area is far cheaper than 10 m.
- **Cache** — repeated `download_*` calls are served from disk; see
  [Caching & configuration](caching.md).
- **Parallelism** — `download_*` functions take a `workers` argument.
