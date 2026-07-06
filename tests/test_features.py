"""Offline tests for the Tier-1 analysis features: time_series, rioxarray
interop, and zonal stats / point sampling.

Rasters are built synthetically with a known CRS/transform so pixel values
at points and polygon aggregates are exact.
"""

from __future__ import annotations

import numpy as np
import pytest

import earthfetch as ef

xr = pytest.importorskip("xarray")
rasterio = pytest.importorskip("rasterio")

from earthfetch.load import _to_dataarray  # noqa: E402
from earthfetch.raster import make_grid  # noqa: E402

# A small AOI in Utah (UTM 12N) and its grid.
BBOX = (-111.90, 40.70, -111.89, 40.708)
CRS = "EPSG:32612"


def _grid():
    return make_grid(BBOX, CRS, 10.0)


def _da(values, name="v"):
    transform, w, h = _grid()
    if values is None:
        values = np.arange(h * w, dtype="float32").reshape(h, w)
    return _to_dataarray(values, transform, w, h, CRS, name, {})


def _banded(nbands=3):
    transform, w, h = _grid()
    data = np.stack([np.full((h, w), i + 1, "float32") for i in range(nbands)])
    da = _to_dataarray(data, transform, w, h, CRS, "img", {})
    return da.assign_coords(band=("band", ["B04", "B03", "B02"][:nbands]))


def _center_lonlat():
    return ((BBOX[0] + BBOX[2]) / 2, (BBOX[1] + BBOX[3]) / 2)


# --------------------------------------------------------------------------
# point sampling
# --------------------------------------------------------------------------

def test_sample_single_point_2d():
    da = _da(None)
    out = ef.sample(da, _center_lonlat())
    assert out.shape == (1,)
    assert np.isfinite(out[0])


def test_sample_matches_manual_index():
    da = _da(None)
    transform = rasterio.transform.Affine(*da.attrs["transform"])
    lon, lat = _center_lonlat()
    xs, ys = rasterio.warp.transform("EPSG:4326", CRS, [lon], [lat])
    row, col = rasterio.transform.rowcol(transform, xs, ys)
    expected = da.values[int(np.atleast_1d(row)[0]), int(np.atleast_1d(col)[0])]
    assert ef.sample(da, (lon, lat))[0] == pytest.approx(expected)


def test_sample_banded_shape():
    da = _banded(3)
    lon, lat = _center_lonlat()
    out = ef.sample(da, [(lon, lat), (lon, lat)])
    assert out.shape == (3, 2)
    assert out[0, 0] == pytest.approx(1.0)
    assert out[2, 1] == pytest.approx(3.0)


def test_sample_point_outside_is_nan():
    da = _da(None)
    out = ef.sample(da, (0.0, 0.0))   # Gulf of Guinea, far outside AOI
    assert np.isnan(out[0])


def test_sample_accepts_geojson_multipoint():
    da = _da(None)
    lon, lat = _center_lonlat()
    mp = {"type": "MultiPoint", "coordinates": [[lon, lat], [lon, lat]]}
    assert ef.sample(da, mp).shape == (2,)


# --------------------------------------------------------------------------
# zonal stats
# --------------------------------------------------------------------------

def _poly_covering_all():
    x0, y0, x1, y1 = BBOX
    return {"type": "Polygon", "coordinates": [[
        [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def test_zonal_constant_raster():
    transform, w, h = _grid()
    da = _to_dataarray(np.full((h, w), 7.0, "float32"), transform, w, h, CRS, "v", {})
    res = ef.zonal_stats(da, _poly_covering_all(),
                         stats=("mean", "min", "max", "count"))
    assert len(res) == 1
    r = res[0]
    assert r["mean"] == pytest.approx(7.0)
    assert r["min"] == pytest.approx(7.0)
    assert r["max"] == pytest.approx(7.0)
    assert r["count"] > 0


def test_zonal_banded_returns_per_band():
    da = _banded(3)
    res = ef.zonal_stats(da, _poly_covering_all(), stats=("mean",))
    r = res[0]
    assert set(r) == {"B04", "B03", "B02"}
    assert r["B04"]["mean"] == pytest.approx(1.0)
    assert r["B02"]["mean"] == pytest.approx(3.0)


def test_zonal_feature_collection_multiple():
    da = _da(None)
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": _poly_covering_all(), "properties": {}},
        {"type": "Feature", "geometry": _poly_covering_all(), "properties": {}},
    ]}
    res = ef.zonal_stats(da, fc, stats=("count",))
    assert len(res) == 2


def test_zonal_unknown_stat_raises():
    da = _da(None)
    with pytest.raises(ef.EarthfetchError):
        ef.zonal_stats(da, _poly_covering_all(), stats=("bogus",))


# --------------------------------------------------------------------------
# rioxarray interop
# --------------------------------------------------------------------------

def test_to_rioxarray_sets_crs():
    pytest.importorskip("rioxarray")
    da = _banded(3)
    rio = ef.to_rioxarray(da)
    assert rio.rio.crs.to_string() == CRS


def test_to_rioxarray_roundtrip_to_raster(tmp_path):
    pytest.importorskip("rioxarray")
    da = _banded(3)
    out = tmp_path / "r.tif"
    ef.to_rioxarray(da).rio.to_raster(out)
    with rasterio.open(out) as ds:
        assert ds.crs.to_string() == CRS
        assert ds.count == 3


def test_reproject_changes_crs():
    pytest.importorskip("rioxarray")
    da = _banded(1).isel(band=0)
    da.attrs = _banded(1).attrs
    out = ef.reproject(da, "EPSG:4326")
    assert out.rio.crs.to_string() == "EPSG:4326"


def test_to_rioxarray_missing_crs_raises():
    pytest.importorskip("rioxarray")
    plain = xr.DataArray(np.ones((4, 4), "float32"), dims=("y", "x"))
    with pytest.raises(ef.EarthfetchError):
        ef.to_rioxarray(plain)


# --------------------------------------------------------------------------
# time_series (HTTP-mocked)
# --------------------------------------------------------------------------

def _mock_scene(scene_id, day, tile, cloud):
    # point band hrefs at a small local COG we create per-test
    return {
        "id": scene_id,
        "properties": {"datetime": f"{day}T18:00:00Z",
                       "eo:cloud_cover": cloud, "grid:code": tile},
        "assets": {},
    }


def test_time_series_stacks_days(monkeypatch, tmp_path):
    """Two acquisition days -> a (time=2, band, y, x) cube, time-ordered."""
    transform, w, h = _grid()

    # a tiny valid COG each band/SCL read can resolve to
    band_tif = tmp_path / "band.tif"
    scl_tif = tmp_path / "scl.tif"
    prof = {"driver": "GTiff", "width": w, "height": h, "count": 1,
            "dtype": "uint16", "crs": CRS, "transform": transform}
    with rasterio.open(band_tif, "w", **prof) as d:
        d.write(np.full((h, w), 2000, "uint16"), 1)
    with rasterio.open(scl_tif, "w", **prof) as d:
        d.write(np.full((h, w), 4, "uint16"), 1)   # 4 = vegetation, valid

    import earthfetch.timeseries as tsmod

    monkeypatch.setattr(tsmod, "search_sentinel2", lambda *a, **k: [
        _mock_scene("s_0501", "2026-05-01", "12TVL", 5),
        _mock_scene("s_0511", "2026-05-11", "12TVL", 3),
    ])
    monkeypatch.setattr(tsmod, "band_url",
                        lambda item, b: str(scl_tif if b == "SCL" else band_tif))

    da = ef.time_series(BBOX, bands=["B04", "B03"], start="2026-05-01",
                        end="2026-05-31")
    assert da.dims == ("time", "band", "y", "x")
    assert da.sizes["time"] == 2
    assert da.sizes["band"] == 2
    assert list(da.band.values) == ["B04", "B03"]
    # time-ordered ascending
    assert da.time.values[0] < da.time.values[1]
    # reflectance-scaled: 2000 DN * 1e-4 = 0.2
    assert float(da.isel(time=0, band=0).mean()) == pytest.approx(0.2, abs=1e-3)
    assert da.attrs["crs"] == CRS


def test_time_series_no_scenes_raises(monkeypatch):
    import earthfetch.timeseries as tsmod
    monkeypatch.setattr(tsmod, "search_sentinel2", lambda *a, **k: [])
    with pytest.raises(ef.NoScenesError):
        ef.time_series(BBOX, start="2026-05-01", end="2026-05-31")
