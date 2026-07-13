"""Phase 2: local vector-file AOIs (shapefile / GeoPackage / KML) with
automatic reprojection to WGS84."""

from __future__ import annotations

import json

import pytest

from earthfetch.aoi import resolve_aoi

fiona = pytest.importorskip("fiona")

# a small square in Salt Lake City, in WGS84 lon/lat
WGS_RING = [(-111.90, 40.70), (-111.88, 40.70), (-111.88, 40.72),
            (-111.90, 40.72), (-111.90, 40.70)]


def _write(path, crs, ring):
    schema = {"geometry": "Polygon", "properties": {"id": "int"}}
    with fiona.open(path, "w", driver=_driver(path), schema=schema, crs=crs) as c:
        c.write({"geometry": {"type": "Polygon", "coordinates": [ring]},
                 "properties": {"id": 1}})


def _driver(path):
    return {"shp": "ESRI Shapefile", "gpkg": "GPKG",
            "geojson": "GeoJSON"}[str(path).rsplit(".", 1)[1]]


def test_shapefile_wgs84(tmp_path):
    p = tmp_path / "aoi.shp"
    _write(p, "EPSG:4326", WGS_RING)
    aoi = resolve_aoi(str(p))
    assert aoi.bbox == pytest.approx((-111.90, 40.70, -111.88, 40.72), abs=1e-6)
    assert aoi.geometry["type"] == "Polygon"
    assert aoi.clip_default is True


def test_geopackage_wgs84(tmp_path):
    p = tmp_path / "aoi.gpkg"
    _write(p, "EPSG:4326", WGS_RING)
    aoi = resolve_aoi(str(p))
    assert aoi.bbox == pytest.approx((-111.90, 40.70, -111.88, 40.72), abs=1e-6)


def test_projected_shapefile_is_reprojected(tmp_path):
    # write the same area in UTM 12N (projected metres); resolve must return
    # WGS84 degrees, not the raw metre coordinates
    from fiona.transform import transform_geom
    utm_geom = transform_geom(
        "EPSG:4326", "EPSG:32612",
        {"type": "Polygon", "coordinates": [WGS_RING]})
    utm_ring = utm_geom["coordinates"][0]
    p = tmp_path / "utm.shp"
    _write(p, "EPSG:32612", utm_ring)

    aoi = resolve_aoi(str(p))
    # must come back as lon/lat degrees near SLC, not ~400000 metre eastings
    assert aoi.bbox == pytest.approx((-111.90, 40.70, -111.88, 40.72), abs=1e-4)
    assert -112 < aoi.bbox[0] < -111


def test_multi_feature_union(tmp_path):
    p = tmp_path / "multi.gpkg"
    schema = {"geometry": "Polygon", "properties": {"id": "int"}}
    ring2 = [(-111.87, 40.73), (-111.85, 40.73), (-111.85, 40.75),
             (-111.87, 40.75), (-111.87, 40.73)]
    with fiona.open(p, "w", driver="GPKG", schema=schema, crs="EPSG:4326") as c:
        for i, ring in enumerate([WGS_RING, ring2]):
            c.write({"geometry": {"type": "Polygon", "coordinates": [ring]},
                     "properties": {"id": i}})
    aoi = resolve_aoi(str(p))
    assert aoi.geometry["type"] == "GeometryCollection"
    # bbox spans both features
    assert aoi.bbox == pytest.approx((-111.90, 40.70, -111.85, 40.75), abs=1e-6)


def test_geojson_still_works_without_extra(tmp_path):
    # GeoJSON path must not require fiona
    p = tmp_path / "aoi.geojson"
    p.write_text(json.dumps({"type": "Polygon", "coordinates": [WGS_RING]}))
    aoi = resolve_aoi(str(p))
    assert aoi.bbox == pytest.approx((-111.90, 40.70, -111.88, 40.72), abs=1e-6)


def test_missing_fiona_message(monkeypatch, tmp_path):
    # simulate fiona not installed -> friendly [vector] message
    import builtins

    from earthfetch.exceptions import MissingDependencyError
    p = tmp_path / "aoi.shp"
    _write(p, "EPSG:4326", WGS_RING)

    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name == "fiona" or name.startswith("fiona."):
            raise ImportError("no fiona")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(MissingDependencyError) as e:
        resolve_aoi(str(p))
    assert "earthfetch[vector]" in str(e.value)
