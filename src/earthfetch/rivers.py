"""River centerlines for any AOI: USGS NHD in the US, OpenStreetMap elsewhere.

Used by ``rem`` to find the channel a Relative Elevation Model is measured
from, and useful on its own for mapping a river corridor. Both sources are
free and keyless.
"""

from __future__ import annotations

from collections import defaultdict

from .exceptions import EarthfetchError, TileNotFoundError
from .utils import get_session, logger, validate_bbox

#: NHD "Flowline - Large Scale" layer (1:24k, US and territories)
NHD_URL = ("https://hydro.nationalmap.gov/arcgis/rest/services/nhd/"
           "MapServer/6/query")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

#: NHD feature types that trace a channel: StreamRiver, ArtificialPath
#: (the centerline through wide rivers and lakes), CanalDitch
_NHD_CHANNEL_FTYPES = {460, 558, 336}


def _nhd_features(bbox) -> list[dict]:
    params = {
        "geometry": ",".join(str(v) for v in bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "gnis_name,ftype,lengthkm",
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "geojson",
    }
    resp = get_session().get(NHD_URL, params=params, timeout=90)
    resp.raise_for_status()
    feats = resp.json().get("features") or []
    out = []
    for f in feats:
        props = f.get("properties") or {}
        if props.get("ftype") not in _NHD_CHANNEL_FTYPES or not f.get("geometry"):
            continue
        out.append({"name": props.get("gnis_name"), "geometry": f["geometry"]})
    logger.info("NHD: %d channel flowline(s) in %s", len(out), tuple(bbox))
    return out


def _osm_features(bbox) -> list[dict]:
    min_lon, min_lat, max_lon, max_lat = bbox
    query = (f'[out:json][timeout:60];way["waterway"~"^(river|stream|canal)$"]'
             f"({min_lat},{min_lon},{max_lat},{max_lon});out geom tags;")
    resp = get_session().post(OVERPASS_URL, data={"data": query}, timeout=90)
    resp.raise_for_status()
    out = []
    for el in resp.json().get("elements", []):
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        tags = el.get("tags", {})
        out.append({
            "name": tags.get("name"),
            "waterway": tags.get("waterway"),
            "geometry": {"type": "LineString",
                         "coordinates": [[p["lon"], p["lat"]] for p in geom]},
        })
    logger.info("OpenStreetMap: %d waterway(s) in %s", len(out), tuple(bbox))
    return out


def _lines(geometry: dict) -> list:
    t = geometry["type"]
    if t == "LineString":
        return [geometry["coordinates"]]
    if t == "MultiLineString":
        return list(geometry["coordinates"])
    return []


def _length_deg(coords) -> float:
    return sum(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
               for (x1, y1, *_), (x2, y2, *_) in zip(coords, coords[1:]))


def _pick_main(features: list[dict], name: str | None) -> tuple[str | None, list]:
    """Lines of the requested river, or of the named river with the most
    length in the AOI (rivers outrank creeks at equal length)."""
    by_name: dict = defaultdict(list)
    for f in features:
        by_name[f.get("name")].extend(_lines(f["geometry"]))
    if name is not None:
        want = name.lower()
        hits = [n for n in by_name if n and want in n.lower()]
        if not hits:
            named = sorted(n for n in by_name if n)
            raise EarthfetchError(
                f"no river named {name!r} in the AOI; found: {named[:12]}"
            )
        lines = [ln for n in hits for ln in by_name[n]]
        return hits[0], lines

    def score(item):
        n, lines = item
        length = sum(_length_deg(ln) for ln in lines)
        is_river = bool(n) and "river" in n.lower()
        return (n is not None, is_river, length)

    best_name, best_lines = max(by_name.items(), key=score)
    return best_name, best_lines


def river_centerline(aoi, name: str | None = None, source: str = "auto") -> dict:
    """Centerline of the main river through an AOI as a GeoJSON Feature.

    Parameters
    ----------
    aoi : bbox, GeoJSON, vector file path, shapely geometry, or place name.
    name : pick a river by (partial, case-insensitive) name, e.g.
        "Colorado". Default: the named river with the most channel length in
        the AOI.
    source : "nhd" (USGS, US only), "osm" (OpenStreetMap, worldwide), or
        "auto" (NHD first, OpenStreetMap when NHD has nothing).

    Returns
    -------
    dict
        GeoJSON Feature with a WGS84 MultiLineString geometry and
        ``name``/``source`` properties.
    """
    from .aoi import resolve_aoi

    bbox = validate_bbox(resolve_aoi(aoi).bbox)
    if source not in ("auto", "nhd", "osm"):
        raise ValueError(f"source must be 'auto', 'nhd', or 'osm', got {source!r}")
    feats: list = []
    used = source
    if source in ("auto", "nhd"):
        try:
            feats = _nhd_features(bbox)
            used = "nhd"
        except Exception as exc:  # outside the US the service errors or is empty
            if source == "nhd":
                raise
            logger.debug("NHD unavailable (%s); trying OpenStreetMap", exc)
    if not feats and source != "nhd":
        feats = _osm_features(bbox)
        used = "osm"
    if not feats:
        raise TileNotFoundError(
            f"no river channels found in {tuple(bbox)}; pass river=<GeoJSON "
            "line> to rem() to supply your own centerline"
        )
    river_name, lines = _pick_main(feats, name)
    logger.info("river_centerline: %s (%s, %d part(s))", river_name, used, len(lines))
    return {
        "type": "Feature",
        "properties": {"name": river_name, "source": used},
        "geometry": {"type": "MultiLineString", "coordinates": lines},
    }
