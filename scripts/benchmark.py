"""Rough, reproducible benchmarks for earthfetch's core operations.

Run: ``python scripts/benchmark.py``. Numbers are network-dependent and
meant to be indicative, not precise — they show the shape of typical
operations and the payoff of windowed COG reads.
"""
from __future__ import annotations

import time

import earthfetch as ef

# small AOIs so a run is quick
SLC = (-111.90, 40.70, -111.88, 40.72)     # ~2 km, Salt Lake City (USGS)
MOAB = (-109.58, 38.56, -109.54, 38.60)    # ~4 km, Moab (Sentinel-2)


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return time.perf_counter() - t, out


def main():
    ef.clear_cache()
    rows = []

    # windowed DEM read vs. the size of the full tile it reads from
    dt, dem = timed(lambda: ef.load_dem(SLC, resolution="10m", crs="utm"))
    tiles = ef.search_dem(SLC, resolution="10m", max_items=1)
    full_mb = tiles[0].get("sizeInBytes", 0) / 1e6
    rows.append(("load_dem (10 m, ~2 km AOI)", dt,
                 f"{dem.shape[1]}x{dem.shape[0]} px; windowed read of a "
                 f"{full_mb:.0f} MB tile, no full download"))

    # elevation: cold vs warm cache
    ct, _ = timed(lambda: ef.elevation((-111.89, 40.71)))
    rows.append(("elevation (1 point, cold)", ct, "loads + samples a DEM"))

    # single Sentinel-2 scene, 3 bands, reflectance
    st, s2 = timed(lambda: ef.load_sentinel2(
        MOAB, bands="true_color", start="2024-06-01", end="2024-08-31", crs="utm"))
    rows.append(("load_sentinel2 (3 bands, ~4 km)", st,
                 f"{s2.shape[2]}x{s2.shape[1]} px, clearest scene"))

    # cloud-free composite (multi-scene blend)
    pt, comp = timed(lambda: ef.composite(
        MOAB, bands="true_color", start="2024-06-01", end="2024-08-31"))
    rows.append(("composite (true color, ~4 km)", pt,
                 f"{len(comp.attrs['dates'])} days blended + SCL-masked"))

    print(f"\n{'operation':34s} {'seconds':>8s}  detail")
    print("-" * 92)
    for name, secs, detail in rows:
        print(f"{name:34s} {secs:8.1f}  {detail}")
    print(f"\ncache after run: {ef.cache_info()}")


if __name__ == "__main__":
    main()
