# Changelog

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
