"""Command-line interface: ``earthfetch dem ...`` and ``earthfetch s2 ...``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import __version__, sentinel, usgs
from .exceptions import EarthfetchError
from .utils import print_progress


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="earthfetch",
        description="Download USGS 3DEP DEMs and Sentinel-2 L2A imagery (no API keys).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="log library activity to stderr")
    sub = parser.add_subparsers(dest="cmd", required=True)

    dem = sub.add_parser("dem", help="USGS 3DEP DEM tiles")
    dem.add_argument("--bbox", type=float, nargs=4, required=True,
                     metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"))
    dem.add_argument("--resolution", default="10m",
                     choices=sorted(usgs.DEM_DATASETS))
    dem.add_argument("--out", default="dem", help="output directory")
    dem.add_argument("--search-only", action="store_true",
                     help="list matching tiles without downloading")
    dem.add_argument("--json", action="store_true", dest="as_json",
                     help="emit search results as JSON (for scripting)")
    dem.add_argument("--max", type=int, default=100, dest="max_items")

    s2 = sub.add_parser("s2", help="Sentinel-2 L2A scenes")
    s2.add_argument("--bbox", type=float, nargs=4, required=True,
                    metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"))
    s2.add_argument("--start", required=True, help="ISO date, e.g. 2026-05-01")
    s2.add_argument("--end", required=True, help="ISO date, e.g. 2026-06-01")
    s2.add_argument("--max-cloud", type=float, default=20.0)
    s2.add_argument("--bands", default="B04,B03,B02",
                    help="comma-separated, e.g. B04,B08 or TCI")
    s2.add_argument("--out", default="sentinel2", help="output directory")
    s2.add_argument("--search-only", action="store_true",
                    help="list matching scenes without downloading")
    s2.add_argument("--json", action="store_true", dest="as_json",
                    help="emit search results as JSON (for scripting)")
    s2.add_argument("--limit", type=int, default=1,
                    help="number of scenes to download (clearest first)")

    args = parser.parse_args(argv)
    if args.verbose:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                            format="%(name)s: %(message)s")

    try:
        return _run(args)
    except EarthfetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run(args) -> int:
    if args.cmd == "dem":
        if args.search_only:
            tiles = usgs.search_dem(args.bbox, args.resolution, args.max_items)
            if args.as_json:
                print(json.dumps(tiles, indent=2))
            else:
                for prod in tiles:
                    mb = prod.get("sizeInBytes", 0) / 1e6
                    print(f"{prod['title']}  ({mb:.0f} MB)")
        else:
            paths = usgs.download_dem(args.bbox, args.resolution, args.out,
                                      args.max_items, progress=print_progress)
            print(f"{len(paths)} tile(s) in {args.out}/")
        return 0

    items = sentinel.search_sentinel2(args.bbox, args.start, args.end,
                                      args.max_cloud,
                                      limit=max(args.limit, 50))
    if args.search_only:
        if args.as_json:
            print(json.dumps([sentinel.scene_summary(i) for i in items], indent=2))
        else:
            for item in items:
                s = sentinel.scene_summary(item)
                print(f"{s['date']}  {s['id']}  cloud={s['cloud_pct']}%")
        return 0
    if not items:
        print("no scenes found", file=sys.stderr)
        return 1
    bands = args.bands.split(",")
    for item in items[: args.limit]:
        files = sentinel.download_sentinel2(item, bands, args.out,
                                            progress=print_progress)
        print(f"{item['id']}: {len(files)} band(s) in {args.out}/{item['id']}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
