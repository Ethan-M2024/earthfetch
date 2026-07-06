"""Tier 1 offline tests: AOI parsing, indices, terrain math, export."""

import json

import numpy as np
import pytest
import xarray as xr

import earthfetch as ef
from earthfetch._composite import _select_day_groups
from earthfetch._terrain import hillshade, slope_aspect
from earthfetch.aoi import AOI, resolve_aoi, utm_crs
from earthfetch.exceptions import EarthfetchError

BOX = (-111.9, 40.7, -111.8, 40.8)
POLY = {
    "type": "Polygon",
    "coordinates": [[[-111.9, 40.7], [-111.8, 40.7], [-111.8, 40.8],
                     [-111.9, 40.8], [-111.9, 40.7]]],
}


# ---- AOI ----

def test_aoi_from_bbox():
    a = resolve_aoi(BOX)
    assert a.bbox == BOX and a.geometry is None


def test_aoi_from_geojson_geometry():
    a = resolve_aoi(POLY)
    assert a.bbox == BOX and a.geometry["type"] == "Polygon"


def test_aoi_from_feature_and_collection():
    feat = {"type": "Feature", "geometry": POLY, "properties": {}}
    fc = {"type": "FeatureCollection", "features": [feat]}
    assert resolve_aoi(feat).bbox == BOX
    assert resolve_aoi(fc).bbox == BOX


def test_aoi_from_file(tmp_path):
    p = tmp_path / "aoi.geojson"
    p.write_text(json.dumps(POLY))
    assert resolve_aoi(str(p)).bbox == BOX


def test_aoi_from_geo_interface():
    class Shape:
        __geo_interface__ = POLY

    assert resolve_aoi(Shape()).bbox == BOX


def test_aoi_rejects_junk():
    with pytest.raises(EarthfetchError):
        resolve_aoi(42)


def test_utm_zones():
    assert utm_crs(BOX) == "EPSG:32612"           # Utah
    assert utm_crs((6.8, 45.8, 6.9, 45.9)) == "EPSG:32632"   # Alps
    assert utm_crs((150.0, -34.0, 150.1, -33.9)) == "EPSG:32756"  # Sydney


# ---- indices ----

def _fake_ds():
    shape = (4, 4)
    def mk(v):
        return xr.DataArray(np.full(shape, v, dtype="float32"),
                                    dims=("y", "x"))
    return xr.Dataset({"B08": mk(0.5), "B04": mk(0.1), "B03": mk(0.2),
                       "B12": mk(0.2), "B02": mk(0.05), "B11": mk(0.3),
                       "B05": mk(0.15)})


def test_ndvi_dataset():
    val = float(ef.ndvi(_fake_ds()).mean())
    assert val == pytest.approx((0.5 - 0.1) / (0.5 + 0.1))


def test_ndvi_banded_dataarray():
    da = _fake_ds().to_array(dim="band")
    assert float(ef.ndvi(da).mean()) == pytest.approx(2 / 3)


def test_index_missing_band():
    with pytest.raises(ef.BandNotFoundError):
        ef.nbr(_fake_ds().drop_vars("B12"))


def test_all_indices_finite():
    ds = _fake_ds()
    for name, fn in ef.INDICES.items():
        assert np.isfinite(fn(ds).values).all(), name


def test_ndmi_value():
    val = float(ef.ndmi(_fake_ds()).mean())
    assert val == pytest.approx((0.5 - 0.3) / (0.5 + 0.3))


def test_ndsi_value():
    val = float(ef.ndsi(_fake_ds()).mean())
    assert val == pytest.approx((0.2 - 0.3) / (0.2 + 0.3))


def test_ndbi_is_negated_ndmi():
    ds = _fake_ds()
    assert float(ef.ndbi(ds).mean()) == pytest.approx(-float(ef.ndmi(ds).mean()))


def test_msavi_bounded():
    vals = ef.msavi(_fake_ds()).values
    assert np.isfinite(vals).all()
    assert ((vals >= -1) & (vals <= 1)).all()


# ---- terrain math ----

def test_flat_dem_zero_slope():
    dem = np.full((10, 10), 100.0, dtype="float32")
    slope, _ = slope_aspect(dem, 10.0)
    assert slope.max() == 0
    assert hillshade(dem, 10.0).min() > 150  # flat ground, sun at 45°


def test_east_facing_ramp():
    # elevation rises to the west -> slope faces east (aspect ~90°)
    dem = np.tile(np.arange(20, 0, -1, dtype="float32") * 10, (20, 1))
    slope, aspect = slope_aspect(dem, 10.0)
    assert slope[5, 5] == pytest.approx(45.0, abs=1)
    assert aspect[5, 5] == pytest.approx(90.0, abs=1)


# ---- composite scene grouping ----

def _item(sid, date, cloud):
    return {"id": sid, "properties": {"datetime": f"{date}T18:00:00Z",
                                      "eo:cloud_cover": cloud}}


def test_day_groups_keep_tiles_together():
    items = [
        _item("a-tile1", "2026-05-01", 5), _item("a-tile2", "2026-05-01", 7),
        _item("b-tile1", "2026-05-06", 50), _item("b-tile2", "2026-05-06", 60),
        _item("c-tile1", "2026-05-11", 1), _item("c-tile2", "2026-05-11", 2),
    ]
    groups = _select_day_groups(items, max_scenes=2)
    picked_days = {g[0]["properties"]["datetime"][:10] for g in groups}
    assert picked_days == {"2026-05-11", "2026-05-01"}  # cloudy day dropped
    assert all(len(g) == 2 for g in groups)  # both tiles kept per day


# ---- export ----

def test_to_geotiff_roundtrip(tmp_path):
    import rasterio

    from earthfetch.load import _to_dataarray

    da = _to_dataarray(
        np.random.rand(4, 5).astype("float32"),
        rasterio.transform.from_origin(500000, 4500000, 30, 30),
        5, 4, "EPSG:32612", "dem", {"units": "m"},
    )
    out = ef.to_geotiff(da, tmp_path / "x.tif")
    with rasterio.open(out) as ds:
        assert ds.crs.to_string() == "EPSG:32612"
        assert (ds.width, ds.height) == (5, 4)


def test_preview_png(tmp_path):
    import rasterio

    from earthfetch.load import _to_dataarray

    da = _to_dataarray(
        np.random.rand(3, 8, 8).astype("float32"),
        rasterio.transform.from_origin(500000, 4500000, 30, 30),
        8, 8, "EPSG:32612", "rgb", {},
    )
    out = ef.preview(da, tmp_path / "p.png")
    assert out.exists() and out.stat().st_size > 100


# ---- NAIP ----

def test_naip_band_order():
    from earthfetch.naip import NAIP_BANDS

    assert NAIP_BANDS == {"R": 1, "G": 2, "B": 3, "N": 4}


def test_sign_url_appends_token(monkeypatch):
    from earthfetch import naip

    monkeypatch.setitem(naip._token, "value", "sig=abc")
    monkeypatch.setitem(naip._token, "expires", 9e9)
    assert naip.sign_url("https://x/a.tif") == "https://x/a.tif?sig=abc"
    assert naip.sign_url("https://x/a.tif?v=1") == "https://x/a.tif?v=1&sig=abc"


def test_geocoded_aoi_defaults_no_clip():
    a = AOI(bbox=BOX, geometry=POLY, clip_default=False)
    assert resolve_aoi(a).clip_default is False
    assert resolve_aoi(POLY).clip_default is True  # explicit polygon clips
