"""Any-AOI input: bbox, GeoJSON (dict or file), shapely geometry, place name.

Every public function accepts these via its ``aoi``/``bbox`` argument:

- ``(min_lon, min_lat, max_lon, max_lat)`` tuple in WGS84
- GeoJSON dict (geometry, Feature, or FeatureCollection)
- path to a ``.geojson``/``.json`` file
- any object with ``__geo_interface__`` (shapely, geopandas rows, ...)
- a place name string — geocoded with OpenStreetMap Nominatim
  ("Moab, UT", "Grand Canyon", "Zermatt")
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from .exceptions import EarthfetchError
from .utils import get_session, logger, validate_bbox

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class AOI(NamedTuple):
    """Resolved area of interest: WGS84 bbox plus optional exact geometry."""

    bbox: tuple[float, float, float, float]
    geometry: dict | None = None  # GeoJSON geometry in WGS84, for masking
    name: str | None = None
    #: whether functions should clip to ``geometry`` when clip=None:
    #: True for polygons the user passed explicitly; False for geocoded
    #: place names, where the boundary is incidental and users expect the
    #: full rectangle
    clip_default: bool = True


def _geom_bounds(geometry: dict) -> tuple[float, float, float, float]:
    def walk(coords):
        if isinstance(coords[0], (int, float)):
            yield coords
        else:
            for c in coords:
                yield from walk(c)

    if geometry.get("type") == "GeometryCollection":
        pts = [p for g in geometry["geometries"] for p in walk(g["coordinates"])]
    else:
        pts = list(walk(geometry["coordinates"]))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return _pad_degenerate(min(xs), min(ys), max(xs), max(ys))


#: half-width (deg, ~11 m) used to give a Point or axis-aligned line a
#: non-zero footprint so it resolves to a valid bbox instead of raising
_DEGENERATE_PAD = 1e-4


def _pad_degenerate(
    minx: float, miny: float, maxx: float, maxy: float
) -> tuple[float, float, float, float]:
    """Expand a zero-width/height extent so ``min < max`` on both axes.

    Points and axis-aligned lines have degenerate bounds; without this a
    valid AOI (e.g. a shapely ``Point``) would fail ``validate_bbox``.
    """
    if maxx <= minx:
        minx, maxx = minx - _DEGENERATE_PAD, maxx + _DEGENERATE_PAD
    if maxy <= miny:
        miny, maxy = miny - _DEGENERATE_PAD, maxy + _DEGENERATE_PAD
    return (minx, miny, maxx, maxy)


def _from_geojson(obj: dict) -> AOI:
    t = obj.get("type")
    if t == "FeatureCollection":
        geoms = [f["geometry"] for f in obj["features"]]
        geometry = (geoms[0] if len(geoms) == 1
                    else {"type": "GeometryCollection", "geometries": geoms})
    elif t == "Feature":
        geometry = obj["geometry"]
    elif t in ("Polygon", "MultiPolygon", "Point", "MultiPoint",
               "LineString", "MultiLineString", "GeometryCollection"):
        geometry = obj
    else:
        raise EarthfetchError(f"unrecognized GeoJSON type: {t!r}")
    return AOI(bbox=validate_bbox(_geom_bounds(geometry)), geometry=geometry)


def geocode(place: str) -> AOI:
    """Resolve a place name to a bbox via OpenStreetMap Nominatim (free)."""
    resp = get_session().get(
        NOMINATIM_URL,
        params={"q": place, "format": "json", "limit": 1, "polygon_geojson": 1},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise EarthfetchError(f"place not found: {place!r}")
    hit = results[0]
    south, north, west, east = (float(v) for v in hit["boundingbox"])
    geometry = hit.get("geojson")
    if geometry and geometry.get("type") not in ("Polygon", "MultiPolygon"):
        geometry = None  # points/lines can't mask an area
    logger.info("geocoded %r -> %s (%s)", place, hit.get("display_name"),
                (west, south, east, north))
    return AOI(bbox=validate_bbox((west, south, east, north)),
               geometry=geometry, name=hit.get("display_name"),
               clip_default=False)


def resolve_aoi(aoi) -> AOI:
    """Normalize any supported AOI input to an ``AOI`` (see module docs)."""
    if isinstance(aoi, AOI):
        return aoi
    if hasattr(aoi, "__geo_interface__"):
        return _from_geojson(dict(aoi.__geo_interface__))
    if isinstance(aoi, dict):
        return _from_geojson(aoi)
    if isinstance(aoi, str) or isinstance(aoi, os.PathLike):
        text = str(aoi)
        low = text.lower()
        if low.endswith((".geojson", ".json")):
            return _from_geojson(json.loads(Path(text).read_text()))
        from .vector import VECTOR_EXTENSIONS
        if low.endswith(VECTOR_EXTENSIONS):
            from .vector import read_vector
            return read_vector(text)
        if Path(text).is_file():
            # a local file with an unfamiliar name — try GeoJSON, else vector
            try:
                return _from_geojson(json.loads(Path(text).read_text()))
            except (ValueError, UnicodeDecodeError):
                from .vector import read_vector
                return read_vector(text)
        return geocode(text)
    if isinstance(aoi, Sequence) and len(aoi) == 4:
        return AOI(bbox=validate_bbox(aoi))
    raise EarthfetchError(
        f"cannot interpret AOI of type {type(aoi).__name__}: pass a bbox "
        "tuple, GeoJSON, a .geojson/.shp/.gpkg path, a shapely geometry, "
        "or a place name"
    )


def utm_crs(bbox: Sequence[float]) -> str:
    """EPSG code of the UTM zone at a bbox center, e.g. 'EPSG:32612'."""
    min_lon, min_lat, max_lon, max_lat = validate_bbox(bbox)
    lon = (min_lon + max_lon) / 2
    lat = (min_lat + max_lat) / 2
    zone = min(60, max(1, math.floor((lon + 180) / 6) + 1))
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def resolve_crs(crs: str, bbox: Sequence[float]) -> str:
    """Expand the 'utm' shorthand to the bbox's UTM zone; pass others through."""
    return utm_crs(bbox) if str(crs).lower() == "utm" else crs
