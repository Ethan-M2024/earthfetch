"""Read an AOI from a local vector file — shapefile, GeoPackage, KML, etc.

GeoJSON files are handled directly by ``resolve_aoi`` (no extra needed).
Other formats are read here with Fiona, and — crucially — reprojected to
WGS84, since shapefiles and GeoPackages usually store a projected CRS.

Requires the ``vector`` extra: ``pip install earthfetch[vector]``.
"""

from __future__ import annotations

import os

from .exceptions import EarthfetchError, MissingDependencyError

#: file extensions routed to this reader (GeoJSON is handled without Fiona)
VECTOR_EXTENSIONS = (".shp", ".gpkg", ".kml", ".gml", ".fgb", ".zip")


def read_vector(path: str | os.PathLike):
    """Read a local vector file into an :class:`~earthfetch.AOI` (WGS84).

    All features are unioned into one AOI geometry; the bbox is their overall
    extent. The file's CRS is read and reprojected to EPSG:4326 automatically.
    """
    from .aoi import AOI, _geom_bounds
    from .utils import validate_bbox

    try:
        import fiona
        from fiona.transform import transform_geom
    except ImportError as exc:  # pragma: no cover
        raise MissingDependencyError(
            "reading shapefiles/GeoPackages/KML needs the optional 'vector' "
            "dependencies; install with: pip install 'earthfetch[vector]' "
            "(GeoJSON files work without it)"
        ) from exc

    src = str(path)
    if src.lower().endswith(".zip"):
        src = "zip://" + src   # a zipped shapefile, read via GDAL's vsizip

    with fiona.open(src) as coll:
        crs = coll.crs
        geoms = [dict(f["geometry"]) for f in coll
                 if f.get("geometry") is not None]

    if not geoms:
        raise EarthfetchError(f"no geometries found in {path!r}")

    # reproject to WGS84 unless the file already is (or has no CRS, in which
    # case we assume lon/lat, as GeoJSON does)
    epsg = crs.to_epsg() if crs else None
    if crs and epsg != 4326:
        geoms = [transform_geom(crs, "EPSG:4326", g) for g in geoms]

    geometry = (geoms[0] if len(geoms) == 1
                else {"type": "GeometryCollection", "geometries": geoms})
    return AOI(
        bbox=validate_bbox(_geom_bounds(geometry)),
        geometry=geometry,
        name=os.path.basename(str(path)),
    )
