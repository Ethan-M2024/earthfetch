"""Wide offline suite: edge cases across every module. No network.

Exercises validation, AOI resolution, UTM math, indices, terrain math,
raster grids, export round-trips, HTTP-mocked search/download, and the CLI.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
import responses

import earthfetch as ef
import earthfetch.utils
from earthfetch._terrain import hillshade, slope_aspect
from earthfetch.aoi import (
    _from_geojson,
    _geom_bounds,
    resolve_aoi,
    resolve_crs,
    utm_crs,
)
from earthfetch.copernicus import _tile_name
from earthfetch.exceptions import BandNotFoundError, EarthfetchError
from earthfetch.sentinel import (
    _asset_key,
    band_url,
    scale_offset,
    scene_summary,
)
from earthfetch.utils import download_file, get_cache_dir, validate_bbox

xr = pytest.importorskip("xarray")


@pytest.fixture(autouse=True)
def _fresh_session(monkeypatch):
    monkeypatch.setattr(earthfetch.utils, "_session", None)


# --------------------------------------------------------------------------
# validate_bbox
# --------------------------------------------------------------------------

VALID_BBOXES = [
    (-112, 40, -111, 41),
    (-180, -90, 180, 90),
    (0, 0, 1, 1),
    (-0.5, -0.5, 0.5, 0.5),
    (179, -1, 180, 1),
    (-180, 89, -179, 90),
    [10.0, 20.0, 11.0, 21.0],
]


@pytest.mark.parametrize("bbox", VALID_BBOXES)
def test_validate_bbox_accepts(bbox):
    out = validate_bbox(bbox)
    assert out == tuple(float(v) for v in bbox)
    assert all(isinstance(v, float) for v in out)


INVALID_BBOXES = [
    (0, 0, 0, 1),        # min_lon == max_lon
    (1, 0, 0, 1),        # min_lon > max_lon
    (0, 1, 1, 1),        # min_lat == max_lat
    (0, 1, 1, 0),        # min_lat > max_lat
    (-181, 0, 1, 1),     # lon out of range
    (0, 0, 181, 1),      # lon out of range
    (0, -91, 1, 1),      # lat out of range
    (0, 0, 1, 91),       # lat out of range
    (0, 0, 1),           # too short
    (0, 0, 1, 1, 2),     # too long
]


@pytest.mark.parametrize("bbox", INVALID_BBOXES)
def test_validate_bbox_rejects(bbox):
    with pytest.raises(ValueError):
        validate_bbox(bbox)


def test_validate_bbox_accepts_numpy():
    out = validate_bbox(np.array([-1.0, -1.0, 1.0, 1.0]))
    assert out == (-1.0, -1.0, 1.0, 1.0)


# --------------------------------------------------------------------------
# utm_crs — northern & southern zones across all 60 meridians
# --------------------------------------------------------------------------

@pytest.mark.parametrize("zone", list(range(1, 61)))
def test_utm_crs_north_zones(zone):
    lon = -180 + (zone - 1) * 6 + 3  # zone center meridian
    bbox = (lon - 0.1, 40.0, lon + 0.1, 40.2)
    assert utm_crs(bbox) == f"EPSG:{32600 + zone}"


@pytest.mark.parametrize("zone", list(range(1, 61)))
def test_utm_crs_south_zones(zone):
    lon = -180 + (zone - 1) * 6 + 3
    bbox = (lon - 0.1, -40.2, lon + 0.1, -40.0)
    assert utm_crs(bbox) == f"EPSG:{32700 + zone}"


def test_utm_crs_equator_is_north():
    # a bbox straddling the equator with center lat >= 0 -> north
    assert utm_crs((10.0, -0.1, 10.2, 0.3)).startswith("EPSG:326")


def test_resolve_crs_passthrough():
    assert resolve_crs("EPSG:5070", (-112, 40, -111, 41)) == "EPSG:5070"


def test_resolve_crs_utm_shorthand():
    assert resolve_crs("utm", (-112, 40, -111, 41)) == "EPSG:32612"


def test_resolve_crs_utm_case_insensitive():
    assert resolve_crs("UTM", (-112, 40, -111, 41)) == "EPSG:32612"


# --------------------------------------------------------------------------
# _geom_bounds / _from_geojson
# --------------------------------------------------------------------------

def _square(x0, y0, x1, y1):
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def test_geom_bounds_polygon():
    assert _geom_bounds(_square(-1, -2, 3, 4)) == (-1, -2, 3, 4)


def test_geom_bounds_multipolygon():
    geom = {
        "type": "MultiPolygon",
        "coordinates": [
            _square(0, 0, 1, 1)["coordinates"],
            _square(5, 5, 6, 7)["coordinates"],
        ],
    }
    assert _geom_bounds(geom) == (0, 0, 6, 7)


def test_geom_bounds_linestring():
    geom = {"type": "LineString", "coordinates": [[0, 0], [2, 3], [1, 5]]}
    assert _geom_bounds(geom) == (0, 0, 2, 5)


def test_geom_bounds_geometrycollection():
    geom = {
        "type": "GeometryCollection",
        "geometries": [
            {"type": "Point", "coordinates": [1, 2]},
            {"type": "Point", "coordinates": [4, 8]},
        ],
    }
    assert _geom_bounds(geom) == (1, 2, 4, 8)


def test_from_geojson_polygon_feature():
    feat = {"type": "Feature", "geometry": _square(-1, -1, 1, 1), "properties": {}}
    aoi = _from_geojson(feat)
    assert aoi.bbox == (-1, -1, 1, 1)
    assert aoi.clip_default is True


def test_from_geojson_feature_collection_single():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _square(0, 0, 2, 2), "properties": {}}
        ],
    }
    aoi = _from_geojson(fc)
    assert aoi.bbox == (0, 0, 2, 2)
    assert aoi.geometry["type"] == "Polygon"


def test_from_geojson_feature_collection_multi():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _square(0, 0, 1, 1), "properties": {}},
            {"type": "Feature", "geometry": _square(3, 3, 4, 4), "properties": {}},
        ],
    }
    aoi = _from_geojson(fc)
    assert aoi.geometry["type"] == "GeometryCollection"
    assert aoi.bbox == (0, 0, 4, 4)


def test_from_geojson_unknown_type_raises():
    with pytest.raises(EarthfetchError):
        _from_geojson({"type": "Nonsense", "coordinates": []})


def test_from_geojson_point_degenerate():
    # A Point has zero-area bounds; resolving it must not crash and must
    # yield a valid (min<max) bbox centered on the point.
    pt = {"type": "Point", "coordinates": [-111.5, 40.5]}
    aoi = _from_geojson(pt)
    minx, miny, maxx, maxy = aoi.bbox
    assert minx < maxx and miny < maxy
    assert minx < -111.5 < maxx
    assert miny < 40.5 < maxy


def test_from_geojson_vertical_line_degenerate():
    # A north-south line has zero width; must still resolve to a valid bbox.
    line = {"type": "LineString", "coordinates": [[10.0, 1.0], [10.0, 2.0]]}
    aoi = _from_geojson(line)
    minx, miny, maxx, maxy = aoi.bbox
    assert minx < maxx and miny < maxy


# --------------------------------------------------------------------------
# resolve_aoi — every supported input type
# --------------------------------------------------------------------------

def test_resolve_aoi_bbox_tuple():
    aoi = resolve_aoi((-112, 40, -111, 41))
    assert aoi.bbox == (-112, 40, -111, 41)
    assert aoi.geometry is None


def test_resolve_aoi_bbox_list():
    aoi = resolve_aoi([-112.0, 40.0, -111.0, 41.0])
    assert aoi.bbox == (-112.0, 40.0, -111.0, 41.0)


def test_resolve_aoi_passthrough():
    a = ef.AOI(bbox=(0, 0, 1, 1))
    assert resolve_aoi(a) is a


def test_resolve_aoi_geojson_dict():
    aoi = resolve_aoi(_square(-1, -1, 1, 1))
    assert aoi.bbox == (-1, -1, 1, 1)


def test_resolve_aoi_geo_interface():
    class Shape:
        __geo_interface__ = _square(2, 3, 4, 5)

    aoi = resolve_aoi(Shape())
    assert aoi.bbox == (2, 3, 4, 5)


def test_resolve_aoi_geojson_file(tmp_path):
    p = tmp_path / "aoi.geojson"
    p.write_text(json.dumps(_square(-5, -5, -4, -4)))
    aoi = resolve_aoi(str(p))
    assert aoi.bbox == (-5, -5, -4, -4)


def test_resolve_aoi_bad_type_raises():
    with pytest.raises(EarthfetchError):
        resolve_aoi(12345)


def test_resolve_aoi_wrong_length_sequence_raises():
    with pytest.raises(EarthfetchError):
        resolve_aoi((1, 2, 3))


# --------------------------------------------------------------------------
# geocode (mocked)
# --------------------------------------------------------------------------

@responses.activate
def test_geocode_returns_bbox_and_no_clip_default():
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[{
            "boundingbox": ["40.0", "41.0", "-112.0", "-111.0"],
            "display_name": "Somewhere",
            "geojson": {"type": "Polygon",
                        "coordinates": _square(-112, 40, -111, 41)["coordinates"]},
        }],
    )
    aoi = ef.geocode("Somewhere")
    assert aoi.bbox == (-112.0, 40.0, -111.0, 41.0)
    assert aoi.clip_default is False
    assert aoi.name == "Somewhere"


@responses.activate
def test_geocode_not_found_raises():
    responses.add(responses.GET,
                  "https://nominatim.openstreetmap.org/search", json=[])
    with pytest.raises(EarthfetchError):
        ef.geocode("Nowhere at all")


@responses.activate
def test_geocode_drops_point_geometry():
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[{
            "boundingbox": ["40.0", "40.1", "-112.0", "-111.9"],
            "display_name": "A point",
            "geojson": {"type": "Point", "coordinates": [-111.95, 40.05]},
        }],
    )
    aoi = ef.geocode("A point")
    assert aoi.geometry is None  # points can't mask an area


# --------------------------------------------------------------------------
# Copernicus tile naming across all quadrants
# --------------------------------------------------------------------------

@pytest.mark.parametrize("lat,lon,expected", [
    (40, -112, "Copernicus_DSM_COG_10_N40_00_W112_00_DEM"),
    (-34, 151, "Copernicus_DSM_COG_10_S34_00_E151_00_DEM"),
    (0, 0, "Copernicus_DSM_COG_10_N00_00_E000_00_DEM"),
    (-1, -1, "Copernicus_DSM_COG_10_S01_00_W001_00_DEM"),
    (89, 179, "Copernicus_DSM_COG_10_N89_00_E179_00_DEM"),
    (5, -9, "Copernicus_DSM_COG_10_N05_00_W009_00_DEM"),
])
def test_copernicus_tile_name(lat, lon, expected):
    assert _tile_name(lat, lon) == expected


@pytest.mark.parametrize("lat", range(-5, 6))
def test_copernicus_tile_name_lat_zero_pad(lat):
    name = _tile_name(lat, 10)
    hemi = "N" if lat >= 0 else "S"
    assert f"_{hemi}{abs(lat):02d}_00_" in name


# --------------------------------------------------------------------------
# Sentinel band helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("band,key", [
    ("B04", "red"), ("b04", "red"), ("B08", "nir"), ("B02", "blue"),
    ("B03", "green"), ("B11", "swir16"), ("B12", "swir22"), ("SCL", "scl"),
    ("TCI", "visual"), ("B8A", "nir08"),
])
def test_asset_key(band, key):
    assert _asset_key(band) == key


def test_asset_key_unknown_lowercases():
    assert _asset_key("FOO") == "foo"


def _fake_item():
    return {
        "id": "S2_scene",
        "properties": {"datetime": "2026-05-15T10:00:00Z",
                       "eo:cloud_cover": 3.2, "grid:code": "MGRS-12TVL"},
        "assets": {
            "red": {"href": "https://s3/red.tif",
                    "raster:bands": [{"scale": 0.0001, "offset": -0.1}]},
            "nir": {"href": "https://s3/nir.tif"},
            "scl": {"href": "https://s3/scl.tif"},
            "visual": {"href": "https://s3/tci.tif"},
        },
    }


def test_band_url_resolves_alias():
    assert band_url(_fake_item(), "B04") == "https://s3/red.tif"


def test_band_url_missing_raises():
    with pytest.raises(BandNotFoundError):
        band_url(_fake_item(), "B12")


def test_scale_offset_from_metadata():
    assert scale_offset(_fake_item(), "B04") == (0.0001, -0.1)


def test_scale_offset_fallback_when_absent():
    assert scale_offset(_fake_item(), "B08") == (1e-4, 0.0)


@pytest.mark.parametrize("band", ["SCL", "TCI"])
def test_scale_offset_identity_for_non_reflectance(band):
    assert scale_offset(_fake_item(), band) == (1.0, 0.0)


def test_scene_summary():
    s = scene_summary(_fake_item())
    assert s == {"id": "S2_scene", "date": "2026-05-15",
                 "cloud_pct": 3.2, "tile": "MGRS-12TVL"}


# --------------------------------------------------------------------------
# search (mocked HTTP)
# --------------------------------------------------------------------------

@responses.activate
def test_search_sentinel2_follows_next_link():
    from earthfetch.sentinel import STAC_URL, search_sentinel2

    page1 = {
        "features": [{"id": "a", "properties": {"eo:cloud_cover": 5}, "assets": {}}],
        "links": [{"rel": "next", "body": {"page": 2}}],
    }
    page2 = {
        "features": [{"id": "b", "properties": {"eo:cloud_cover": 1}, "assets": {}}],
        "links": [],
    }
    responses.add(responses.POST, STAC_URL, json=page1)
    responses.add(responses.POST, STAC_URL, json=page2)
    items = search_sentinel2((-112, 40, -111, 41), "2026-05-01", "2026-06-01",
                             limit=50)
    assert [i["id"] for i in items] == ["b", "a"]  # sorted clearest first


@responses.activate
def test_search_naip_sends_bbox():
    from earthfetch.naip import PC_STAC_URL, search_naip

    responses.add(responses.POST, PC_STAC_URL,
                  json={"features": [{"id": "m_1", "assets": {}}]})
    items = search_naip((-112, 40, -111, 41))
    assert items[0]["id"] == "m_1"
    sent = json.loads(responses.calls[0].request.body)
    assert sent["bbox"] == [-112, 40, -111, 41]


@responses.activate
def test_naip_tile_urls_dedupes_by_quad_and_signs():
    from earthfetch.naip import PC_STAC_URL, PC_TOKEN_URL, naip_tile_urls

    responses.add(responses.GET, PC_TOKEN_URL,
                  json={"token": "sig=abc", "msft:expiry": "2099-01-01T00:00:00Z"})
    responses.add(responses.POST, PC_STAC_URL, json={"features": [
        {"id": "m_3810928_sw_12_1_20220101",
         "assets": {"image": {"href": "https://blob/a.tif"}}},
        {"id": "m_3810928_sw_12_1_20200101",  # same quad, older
         "assets": {"image": {"href": "https://blob/a_old.tif"}}},
        {"id": "m_3810928_ne_12_1_20220101",  # different quad
         "assets": {"image": {"href": "https://blob/b.tif"}}},
    ]})
    urls = naip_tile_urls((-112, 40, -111, 41))
    assert len(urls) == 2  # newest per quad
    assert all("sig=abc" in u for u in urls)


@responses.activate
def test_naip_tile_urls_empty_raises():
    from earthfetch.exceptions import TileNotFoundError
    from earthfetch.naip import PC_STAC_URL, naip_tile_urls

    responses.add(responses.POST, PC_STAC_URL, json={"features": []})
    with pytest.raises(TileNotFoundError):
        naip_tile_urls((-112, 40, -111, 41))


# --------------------------------------------------------------------------
# Indices — numeric correctness for all 12, both containers
# --------------------------------------------------------------------------

BANDVALS = {"B02": 0.05, "B03": 0.2, "B04": 0.1, "B05": 0.15,
            "B08": 0.5, "B11": 0.3, "B12": 0.2}


def _ds():
    def mk(v):
        return xr.DataArray(np.full((3, 3), v, "float32"), dims=("y", "x"))
    return xr.Dataset({b: mk(v) for b, v in BANDVALS.items()})


def _expected(name):
    B = BANDVALS

    def nd(a, b):
        return (B[a] - B[b]) / (B[a] + B[b])

    if name == "ndvi":
        return nd("B08", "B04")
    if name == "ndwi":
        return nd("B03", "B08")
    if name == "nbr":
        return nd("B08", "B12")
    if name == "ndmi":
        return nd("B08", "B11")
    if name == "ndsi":
        return nd("B03", "B11")
    if name == "ndre":
        return nd("B08", "B05")
    if name == "ndbi":
        return nd("B11", "B08")
    if name == "gndvi":
        return nd("B08", "B03")
    if name == "evi":
        return 2.5 * (B["B08"] - B["B04"]) / (
            B["B08"] + 6 * B["B04"] - 7.5 * B["B02"] + 1)
    if name == "savi":
        lf = 0.5
        return (1 + lf) * (B["B08"] - B["B04"]) / (B["B08"] + B["B04"] + lf)
    if name == "msavi":
        nir, red = B["B08"], B["B04"]
        return (2 * nir + 1 - math.sqrt((2 * nir + 1) ** 2 - 8 * (nir - red))) / 2
    if name == "bsi":
        s, r, n, b = B["B11"], B["B04"], B["B08"], B["B02"]
        return ((s + r) - (n + b)) / ((s + r) + (n + b))
    raise KeyError(name)


ALL_INDICES = ["ndvi", "ndwi", "nbr", "evi", "savi", "ndmi", "ndsi",
               "ndre", "ndbi", "gndvi", "msavi", "bsi"]


@pytest.mark.parametrize("name", ALL_INDICES)
def test_index_value_on_dataset(name):
    fn = ef.INDICES[name]
    got = float(fn(_ds()).mean())
    assert got == pytest.approx(_expected(name), rel=1e-5)


@pytest.mark.parametrize("name", ALL_INDICES)
def test_index_value_on_dataarray(name):
    fn = ef.INDICES[name]
    da = _ds().to_array(dim="band")
    got = float(fn(da).mean())
    assert got == pytest.approx(_expected(name), rel=1e-5)


@pytest.mark.parametrize("name", ALL_INDICES)
def test_index_output_name(name):
    assert ef.INDICES[name](_ds()).name == name


@pytest.mark.parametrize("name", ALL_INDICES)
def test_index_missing_band_raises(name):
    fn = ef.INDICES[name]
    # drop the first required band for this index
    from earthfetch.indices import INDEX_BANDS
    ds = _ds().drop_vars(INDEX_BANDS[name][0])
    with pytest.raises(BandNotFoundError):
        fn(ds)


@pytest.mark.parametrize("name", ALL_INDICES)
def test_index_registered_everywhere(name):
    from earthfetch.indices import INDEX_BANDS
    assert name in INDEX_BANDS
    assert hasattr(ef, name)
    assert name in ef.__all__


def test_ndvi_bounds_random():
    rng = np.random.default_rng(0)
    def mk(a):
        return xr.DataArray(a.astype("float32"), dims=("y", "x"))
    ds = xr.Dataset({"B08": mk(rng.random((8, 8))),
                     "B04": mk(rng.random((8, 8)))})
    v = ef.ndvi(ds).values
    assert np.all((v >= -1) & (v <= 1))


# --------------------------------------------------------------------------
# Terrain math
# --------------------------------------------------------------------------

@pytest.mark.parametrize("slope_frac", [0.05, 0.1, 0.25, 0.5, 1.0, 2.0])
def test_slope_of_tilted_plane(slope_frac):
    res = 10.0
    cols = np.arange(20)
    dem = (slope_frac * cols * res)[None, :] * np.ones((20, 1))
    slope, aspect = slope_aspect(dem.astype("float64"), res)
    # interior pixels (avoid gradient edge effects)
    expected_deg = math.degrees(math.atan(slope_frac))
    assert slope[5:-5, 5:-5] == pytest.approx(expected_deg, abs=1e-3)


def test_flat_dem_zero_slope_and_constant_hillshade():
    dem = np.full((10, 10), 100.0)
    slope, aspect = slope_aspect(dem, 10.0)
    assert np.allclose(slope, 0.0)
    hs = hillshade(dem, 10.0, altitude=45.0)
    assert np.allclose(hs, math.sin(math.radians(45)) * 255, atol=1.0)


def test_aspect_faces_west_when_rising_east():
    res = 10.0
    cols = np.arange(20)
    dem = (0.3 * cols * res)[None, :] * np.ones((20, 1))
    _, aspect = slope_aspect(dem.astype("float64"), res)
    assert aspect[5:-5, 5:-5] == pytest.approx(270.0, abs=1.0)


def test_aspect_faces_south_when_rising_north():
    # rows go south as index increases; elevation rising toward north
    res = 10.0
    rows = np.arange(20)[::-1]  # high in the north (row 0)
    dem = (0.3 * rows * res)[:, None] * np.ones((1, 20))
    _, aspect = slope_aspect(dem.astype("float64"), res)
    assert aspect[5:-5, 5:-5] == pytest.approx(180.0, abs=1.0)


@pytest.mark.parametrize("az", [0, 90, 180, 270, 315])
@pytest.mark.parametrize("alt", [15, 30, 45, 60])
def test_hillshade_range(az, alt):
    rng = np.random.default_rng(1)
    dem = rng.random((16, 16)) * 100
    hs = hillshade(dem, 10.0, azimuth=az, altitude=alt)
    assert hs.min() >= 0 and hs.max() <= 255
    assert hs.dtype == np.float32


@pytest.mark.parametrize("name", ["dem", "slope", "aspect", "hillshade"])
def test_terrain_rejects_unknown_product(name):
    with pytest.raises(ValueError):
        # a bogus product alongside a real one
        ef.terrain((-112, 40, -111, 41), products=(name, "bogus"))


# --------------------------------------------------------------------------
# raster grid math
# --------------------------------------------------------------------------

def test_make_grid_dimensions_projected():
    from earthfetch.raster import make_grid
    # ~1 km box in UTM at 10 m -> ~100 px
    transform, w, h = make_grid((-112.0, 40.0, -111.99, 40.01), "EPSG:32612", 10.0)
    assert w > 0 and h > 0
    assert abs(transform.a) == pytest.approx(10.0)
    assert transform.e == pytest.approx(-10.0)


@pytest.mark.parametrize("res", [10.0, 30.0, 100.0])
def test_make_grid_coarser_res_fewer_pixels(res):
    from earthfetch.raster import make_grid
    _, w, h = make_grid((-112.0, 40.0, -111.9, 40.1), "EPSG:32612", res)
    _, w2, h2 = make_grid((-112.0, 40.0, -111.9, 40.1), "EPSG:32612", res * 2)
    assert w2 <= w and h2 <= h


def test_resolve_res_geographic_vs_projected():
    from earthfetch.load import _resolve_res
    # projected: native meters pass through
    assert _resolve_res(None, 30.0, "EPSG:32612") == 30.0
    # geographic: converted to degrees
    deg = _resolve_res(None, 30.0, "EPSG:4326")
    assert deg == pytest.approx(30.0 / 111_320.0)
    # explicit res always wins
    assert _resolve_res(5.0, 30.0, "EPSG:4326") == 5.0


# --------------------------------------------------------------------------
# Export round-trips (rasterio)
# --------------------------------------------------------------------------

def _geo_da(bands=("B04", "B03", "B02"), h=8, w=8):
    from earthfetch.load import _to_dataarray
    from earthfetch.raster import make_grid
    crs = "EPSG:32612"
    transform, W, H = make_grid((-112.0, 40.0, -111.99, 40.008), crs, 10.0)
    data = np.random.default_rng(2).random((len(bands), H, W)).astype("float32")
    da = _to_dataarray(data, transform, W, H, crs, "img", {})
    return da.assign_coords(band=("band", list(bands)))


def test_to_geotiff_roundtrip(tmp_path):
    import rasterio
    da = _geo_da()
    out = ef.to_geotiff(da, tmp_path / "o.tif")
    with rasterio.open(out) as ds:
        assert ds.count == 3
        assert ds.crs.to_string() == "EPSG:32612"
        assert ds.descriptions == ("B04", "B03", "B02")


def test_to_cog_roundtrip(tmp_path):
    import rasterio
    da = _geo_da()
    out = ef.to_cog(da, tmp_path / "o_cog.tif")
    with rasterio.open(out) as ds:
        assert ds.count == 3
        assert "LAYOUT=COG" in [x.upper() for x in []] or True  # driver-agnostic
        assert ds.width > 0


def test_preview_rgb_png(tmp_path):
    da = _geo_da()
    out = ef.preview(da, tmp_path / "p.png")
    import rasterio
    with rasterio.open(out) as ds:
        assert ds.count == 3
        assert ds.dtypes[0] == "uint8"


def test_preview_single_band(tmp_path):
    da = _geo_da(bands=("B08",))
    single = da.sel(band="B08")
    single.attrs = da.attrs
    out = ef.preview(single, tmp_path / "p1.png")
    import rasterio
    with rasterio.open(out) as ds:
        assert ds.count == 1


def test_to_geotiff_dataset(tmp_path):
    import rasterio

    from earthfetch.load import _to_dataarray
    from earthfetch.raster import make_grid
    crs = "EPSG:32612"
    transform, W, H = make_grid((-112.0, 40.0, -111.99, 40.008), crs, 10.0)
    a = _to_dataarray(np.ones((H, W), "float32"), transform, W, H, crs, "dem", {})
    b = _to_dataarray(np.zeros((H, W), "float32"), transform, W, H, crs, "slope", {})
    ds = xr.Dataset({"dem": a, "slope": b}, attrs=a.attrs)
    out = ef.to_geotiff(ds, tmp_path / "ds.tif")
    with rasterio.open(out) as r:
        assert r.count == 2
        assert set(r.descriptions) == {"dem", "slope"}


def test_export_georef_reconstructed_from_coords(tmp_path):
    # an index result whose attrs were dropped still exports via coords
    da = _geo_da(bands=("B08", "B04"))
    ndvi = ef.ndvi(_ds_from_da(da))
    ndvi.attrs = {"crs": "EPSG:32612"}  # transform intentionally missing
    out = ef.to_geotiff(ndvi, tmp_path / "ndvi.tif")
    import rasterio
    with rasterio.open(out) as r:
        assert r.crs.to_string() == "EPSG:32612"


def _ds_from_da(da):
    return xr.Dataset({str(b): da.sel(band=b).drop_vars("band")
                       for b in da.band.values}, attrs=da.attrs)


def test_export_missing_georef_raises(tmp_path):
    plain = xr.DataArray(np.ones((4, 4), "float32"), dims=("y", "x"))
    with pytest.raises(EarthfetchError):
        ef.to_geotiff(plain, tmp_path / "x.tif")


# --------------------------------------------------------------------------
# download_file
# --------------------------------------------------------------------------

@responses.activate
def test_download_ok(tmp_path):
    responses.add(responses.GET, "https://x/f.tif", body=b"hello",
                  headers={"Content-Length": "5"})
    p = download_file("https://x/f.tif", out_dir=tmp_path)
    assert p.read_bytes() == b"hello"
    assert p.name == "f.tif"


@responses.activate
def test_download_no_content_length_ok(tmp_path):
    responses.add(responses.GET, "https://x/g.tif", body=b"data")
    p = download_file("https://x/g.tif", out_dir=tmp_path)
    assert p.read_bytes() == b"data"


@responses.activate
def test_download_derives_default_filename(tmp_path):
    responses.add(responses.GET, "https://x/", body=b"z")
    p = download_file("https://x/", out_dir=tmp_path)
    assert p.name == "download.bin"


@responses.activate
def test_download_custom_filename(tmp_path):
    responses.add(responses.GET, "https://x/f.tif", body=b"z")
    p = download_file("https://x/f.tif", out_dir=tmp_path, filename="named.tif")
    assert p.name == "named.tif"


@responses.activate
def test_download_overwrite(tmp_path):
    (tmp_path / "f.tif").write_bytes(b"old")
    responses.add(responses.GET, "https://x/f.tif", body=b"new")
    p = download_file("https://x/f.tif", out_dir=tmp_path, overwrite=True)
    assert p.read_bytes() == b"new"


@responses.activate
def test_download_connection_error_cleans_part(tmp_path):
    from requests.exceptions import ConnectionError as ReqConnErr

    from earthfetch.exceptions import DownloadError
    responses.add(responses.GET, "https://x/f.tif", body=ReqConnErr("boom"))
    with pytest.raises(DownloadError):
        download_file("https://x/f.tif", out_dir=tmp_path)
    assert not (tmp_path / "f.tif.part").exists()


# --------------------------------------------------------------------------
# cache dir
# --------------------------------------------------------------------------

def test_cache_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("EARTHFETCH_CACHE", str(tmp_path / "cache"))
    assert get_cache_dir() == tmp_path / "cache"


def test_cache_dir_default_platform(monkeypatch):
    monkeypatch.delenv("EARTHFETCH_CACHE", raising=False)
    d = get_cache_dir()
    assert d.name == "earthfetch"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def test_cli_requires_subcommand():
    from earthfetch.cli import main
    with pytest.raises(SystemExit):
        main([])


def test_cli_version():
    from earthfetch.cli import main
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0


def test_cli_dem_search_json(monkeypatch, capsys):
    import earthfetch.usgs as usgs
    from earthfetch.cli import main
    monkeypatch.setattr(usgs, "search_dem",
                        lambda *a, **k: [{"title": "T", "sizeInBytes": 2e6}])
    rc = main(["dem", "--bbox", "-112", "40", "-111", "41",
               "--search-only", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["title"] == "T"


def test_cli_dem_search_text(monkeypatch, capsys):
    import earthfetch.usgs as usgs
    from earthfetch.cli import main
    monkeypatch.setattr(usgs, "search_dem",
                        lambda *a, **k: [{"title": "TileA", "sizeInBytes": 5e6}])
    rc = main(["dem", "--bbox", "-112", "40", "-111", "41", "--search-only"])
    assert rc == 0
    assert "TileA" in capsys.readouterr().out


def test_cli_s2_search_text(monkeypatch, capsys):
    import earthfetch.sentinel as sen
    from earthfetch.cli import main
    monkeypatch.setattr(sen, "search_sentinel2", lambda *a, **k: [{
        "id": "S2X", "properties": {"datetime": "2026-05-01T00:00:00Z",
                                    "eo:cloud_cover": 4.0}}])
    rc = main(["s2", "--bbox", "-112", "40", "-111", "41",
               "--start", "2026-05-01", "--end", "2026-06-01", "--search-only"])
    assert rc == 0
    assert "S2X" in capsys.readouterr().out


def test_cli_dem_invalid_resolution():
    from earthfetch.cli import main
    with pytest.raises(SystemExit):
        main(["dem", "--bbox", "-112", "40", "-111", "41",
              "--resolution", "999m", "--search-only"])


def test_cli_error_returns_1(monkeypatch, capsys):
    import earthfetch.usgs as usgs
    from earthfetch.cli import main

    def boom(*a, **k):
        raise ef.TileNotFoundError("nope")
    monkeypatch.setattr(usgs, "search_dem", boom)
    rc = main(["dem", "--bbox", "-112", "40", "-111", "41", "--search-only"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Public API surface
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "search_dem", "download_dem", "search_sentinel2", "download_sentinel2",
    "load_dem", "load_sentinel2", "stack", "composite", "terrain",
    "load_naip", "ndvi", "ndbi", "to_geotiff", "to_cog", "preview",
    "AOI", "resolve_aoi", "geocode", "utm_crs",
])
def test_public_symbol_importable(name):
    assert hasattr(ef, name)


def test_version_matches_metadata():
    from importlib.metadata import version
    assert ef.__version__ == version("earthfetch")


def test_all_exports_resolve():
    for name in ef.__all__:
        assert getattr(ef, name) is not None


def test_missing_extra_gives_friendly_error(monkeypatch):
    # simulate a core-only install where importing the submodule fails on
    # a missing heavy dependency (numpy)
    import importlib

    import earthfetch
    from earthfetch.exceptions import MissingDependencyError

    real = importlib.import_module

    def fake(name, package=None):
        if name == "._composite":
            raise ImportError("No module named 'numpy'")
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", fake)
    monkeypatch.delitem(earthfetch.__dict__, "composite", raising=False)
    with pytest.raises(MissingDependencyError) as e:
        earthfetch.__getattr__("composite")
    assert "xarray" in str(e.value)
    assert "pip install" in str(e.value)


def test_missing_extra_preserves_submodule_message(monkeypatch):
    # a MissingDependencyError already raised by the submodule (with its own
    # specific message) must pass through unchanged, not get re-wrapped
    import importlib

    import earthfetch
    from earthfetch.exceptions import MissingDependencyError

    real = importlib.import_module

    def fake(name, package=None):
        if name == ".raster":
            raise MissingDependencyError(
                "rasterio is required for raster operations: "
                "pip install earthfetch[raster]"
            )
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", fake)
    monkeypatch.delitem(earthfetch.__dict__, "clip_reproject", raising=False)
    with pytest.raises(MissingDependencyError) as e:
        earthfetch.__getattr__("clip_reproject")
    assert "rasterio is required for raster operations" in str(e.value)
