"""Interactive demo: pick a bbox anywhere on Earth, a CRS, and resolutions.

Run:  python examples/interactive_fetch.py
Every prompt has a default — press Enter to accept it.

Uses the windowed array API: only your bbox travels over the network.
Writes pixel-aligned GeoTIFFs clipped to the bbox in your chosen CRS.
"""

import logging
import sys

import earthfetch as ef
from earthfetch.raster import make_grid, write_geotiff

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

#: Sentinel-2 band groups by native resolution
S2_RES_BANDS = {
    "10m": ["B02", "B03", "B04", "B08"],
    "20m": ["B05", "B06", "B07", "B8A", "B11", "B12", "SCL"],
    "60m": ["B01", "B09"],
}


def ask(prompt, default):
    val = input(f"{prompt} [{default}]: ").strip()
    return val or default


def main():
    print("=== earthfetch interactive demo ===\n")

    raw = ask("bbox min_lon min_lat max_lon max_lat", "-111.90 40.70 -111.85 40.75")
    bbox = tuple(float(v) for v in raw.replace(",", " ").split())

    dst_crs = ask("target CRS", "EPSG:32612")
    res = float(ask("pixel size (CRS units)", "30"))
    out_dir = ask("output directory", "fetched")
    tag = dst_crs.replace(":", "")

    # ---- DEM ----
    dem_res = ask(f"DEM resolution {sorted(ef.DEM_DATASETS)} or 'skip'", "30m")
    if dem_res != "skip":
        dem = ef.load_dem(bbox, resolution=dem_res, crs=dst_crs, res=res)
        out = write_geotiff(
            f"{out_dir}/dem_{dem.attrs['source']}_{tag}.tif",
            dem.values, make_grid(bbox, dst_crs, res)[0], dst_crs,
            nodata=float("nan"),
            tags={"EARTHFETCH_SOURCES": ",".join(dem.attrs["sources"])},
        )
        print(f"  DEM ({dem.attrs['source']}) ready: {out}")

    # ---- Sentinel-2 ----
    s2_res = ask("Sentinel-2 resolution 10m/20m/60m or 'skip'", "10m")
    if s2_res == "skip":
        return
    start = ask("start date", "2026-05-01")
    end = ask("end date", "2026-06-01")
    max_cloud = float(ask("max cloud %", "20"))

    scenes = ef.search_sentinel2(bbox, start, end, max_cloud=max_cloud)
    if not scenes:
        print("  no scenes found — widen dates or raise cloud limit")
        return
    for s in scenes[:5]:
        info = ef.scene_summary(s)
        print(f"  {info['date']}  {info['id']}  cloud={info['cloud_pct']}%")
    best = scenes[0]
    print(f"  using clearest: {best['id']}")

    bands = S2_RES_BANDS[s2_res]
    raw = ask(f"bands (subset of {bands})", " ".join(bands[:2]))
    bands = raw.replace(",", " ").split()

    s2 = ef.load_sentinel2(bbox, bands=bands, crs=dst_crs, res=res, item=best)
    for band in s2.band.values:
        out = write_geotiff(
            f"{out_dir}/s2_{band}_{tag}.tif",
            s2.sel(band=band).values,
            make_grid(bbox, dst_crs, res)[0], dst_crs,
            nodata=float("nan"),
            tags={"EARTHFETCH_SCENE": best["id"]},
        )
        print(f"  {band} ready: {out}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\naborted")
    except ef.EarthfetchError as exc:
        sys.exit(f"error: {exc}")
