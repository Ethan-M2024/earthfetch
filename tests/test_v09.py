"""0.9.0: ArcticDEM/REMA, Sentinel-1 SAR, river centerlines, REM, colormapped
previews. Network is mocked; local COGs stand in for remote assets."""

from __future__ import annotations

import numpy as np
import pytest
import responses

import earthfetch as ef
import earthfetch.utils

xr = pytest.importorskip("xarray")
rasterio = pytest.importorskip("rasterio")

from earthfetch.raster import make_grid  # noqa: E402

BBOX = (-111.90, 40.70, -111.88, 40.715)
CRS = "EPSG:32612"


@pytest.fixture(autouse=True)
def fresh_session(monkeypatch):
    monkeypatch.setattr(earthfetch.utils, "_session", None)


def _write(path, arr, res, crs=CRS, bbox=BBOX, dtype="float32", nodata=None):
    transform, w, h = make_grid(bbox, crs, res)
    if callable(arr):
        arr = arr(h, w, transform)
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1,
                       dtype=dtype, crs=crs, transform=transform,
                       nodata=nodata) as d:
        d.write(np.broadcast_to(arr, (h, w)).astype(dtype), 1)
    return path


# ---------------------------------------------------------------- polar DEMs

def test_polar_region_by_hemisphere():
    from earthfetch.polar import polar_region

    assert polar_region((-148, 64, -147, 65)) == "arcticdem"
    assert polar_region((166, -78, 167, -77)) == "rema"


@responses.activate
def test_search_polar_dem_follows_paging_and_picks_collection():
    from earthfetch.polar import PGC_STAC_URL, polar_dem_urls

    def item(i):
        return {"id": f"t{i}", "assets": {"dem": {"href": f"https://x/{i}_dem.tif"}}}

    responses.add(responses.POST, PGC_STAC_URL, json={
        "features": [item(1)],
        "links": [{"rel": "next", "href": "https://stac.pgc.umn.edu/next",
                   "method": "GET"}]})
    responses.add(responses.GET, "https://stac.pgc.umn.edu/next",
                  json={"features": [item(2)], "links": []})
    urls = polar_dem_urls((-148, 64.8, -147.9, 64.9), resolution="2m")
    assert urls == ["https://x/1_dem.tif", "https://x/2_dem.tif"]
    import json
    body = json.loads(responses.calls[0].request.body)
    assert body["collections"] == ["arcticdem-mosaics-v4.1-2m"]


@responses.activate
def test_polar_dem_urls_empty_raises():
    from earthfetch.polar import PGC_STAC_URL, polar_dem_urls

    responses.add(responses.POST, PGC_STAC_URL, json={"features": []})
    with pytest.raises(ef.TileNotFoundError):
        polar_dem_urls((-148, 64.8, -147.9, 64.9))


def test_polar_bad_resolution():
    from earthfetch.polar import search_polar_dem

    with pytest.raises(ValueError):
        search_polar_dem((-148, 64.8, -147.9, 64.9), resolution="30m")


def test_load_dem_polar_source(tmp_path, monkeypatch):
    tif = _write(tmp_path / "a.tif", 123.0, 10.0)
    import earthfetch.polar as polar

    monkeypatch.setattr(polar, "polar_dem_urls",
                        lambda bbox, resolution, region: [str(tif)])
    dem = ef.load_dem(BBOX, resolution="10M", crs=CRS, source="arcticdem")
    assert dem.attrs["source"] == "arcticdem"
    assert dem.attrs["resolution"] == "10m"
    assert float(dem.mean()) == pytest.approx(123.0)


def test_load_dem_unknown_source():
    with pytest.raises(ValueError, match="unknown DEM source"):
        ef.load_dem(BBOX, source="srtm")


# --------------------------------------------------------------- Sentinel-1

def _s1_item(i, date, orbit=20, platform="sentinel-1a", vv=None, vh=None):
    return {"id": f"S1_{i}",
            "properties": {"datetime": f"{date}T01:00:00Z",
                           "sat:relative_orbit": orbit, "platform": platform,
                           "sat:orbit_state": "ascending",
                           "sar:polarizations": ["VV", "VH"]},
            "assets": {"vv": {"href": str(vv)}, "vh": {"href": str(vh)}}}


def test_acquisition_passes_group_by_day_and_orbit():
    from earthfetch.sentinel1 import acquisition_passes

    items = [_s1_item(1, "2026-09-01"), _s1_item(2, "2026-09-01"),
             _s1_item(3, "2026-09-07"), _s1_item(4, "2026-09-01", orbit=93)]
    passes = acquisition_passes(items)
    assert [len(p) for p in passes][0] == 1          # newest first
    assert passes[0][0]["id"] == "S1_3"
    assert sorted(len(p) for p in passes) == [1, 1, 2]


def test_load_sentinel1_db_and_median(tmp_path, monkeypatch):
    import earthfetch.landsat as lsmod

    monkeypatch.setattr(lsmod, "sign_mpc", lambda href: href)
    a = _write(tmp_path / "a.tif", 0.1, 10.0)       # -10 dB
    b = _write(tmp_path / "b.tif", 0.01, 10.0)      # -20 dB
    c = _write(tmp_path / "c.tif", 0.1, 10.0)
    items = [_s1_item(1, "2026-09-11", vv=a, vh=b),
             _s1_item(2, "2026-09-05", vv=b, vh=b),
             _s1_item(3, "2026-08-30", vv=c, vh=b)]

    latest = ef.load_sentinel1(BBOX, items=items, crs=CRS)
    assert list(latest.band.values) == ["VV", "VH"]
    assert float(latest.sel(band="VV").mean()) == pytest.approx(-10.0, abs=1e-4)
    assert latest.attrs["dates"] == ["2026-09-11"]

    med = ef.load_sentinel1(BBOX, items=items, crs=CRS, method="median",
                            polarizations=["VV"], db=False)
    assert float(med.mean()) == pytest.approx(0.1, abs=1e-6)  # median(.1,.01,.1)
    assert med.attrs["units"] == "linear"
    assert len(med.attrs["dates"]) == 3


def test_load_sentinel1_masks_fill(tmp_path, monkeypatch):
    import earthfetch.landsat as lsmod

    monkeypatch.setattr(lsmod, "sign_mpc", lambda href: href)

    def half_fill(h, w, _):
        arr = np.full((h, w), 0.05, "float32")
        arr[:, : w // 2] = -32768
        return arr

    a = _write(tmp_path / "a.tif", half_fill, 10.0)
    da = ef.load_sentinel1(BBOX, items=[_s1_item(1, "2026-09-11", vv=a, vh=a)],
                           crs=CRS, polarizations=["VV"])
    assert np.isnan(da.values).mean() == pytest.approx(0.5, abs=0.05)


def test_load_sentinel1_argument_errors():
    with pytest.raises(ValueError):
        ef.load_sentinel1(BBOX, crs=CRS)
    with pytest.raises(ValueError):
        ef.load_sentinel1(BBOX, crs=CRS, start="2026-01-01", end="2026-02-01",
                          method="mean")
    with pytest.raises(ef.BandNotFoundError):
        ef.load_sentinel1(BBOX, crs=CRS, polarizations=["XX"],
                          start="2026-01-01", end="2026-02-01")


@responses.activate
def test_load_sentinel1_no_scenes():
    from earthfetch.sentinel1 import PC_STAC_URL

    responses.add(responses.POST, PC_STAC_URL, json={"features": []})
    with pytest.raises(ef.NoScenesError):
        ef.load_sentinel1(BBOX, crs=CRS, start="2026-01-01", end="2026-01-02")


def test_water_mask_threshold():
    data = np.array([[[-25.0, -10.0], [np.nan, -19.0]]], dtype="float32")
    da = xr.DataArray(data, dims=("band", "y", "x"),
                      coords={"band": ["VV"], "y": [1, 0], "x": [0, 1]},
                      attrs={"units": "dB", "crs": CRS,
                             "transform": (10, 0, 0, 0, -10, 20)})
    w = ef.water_mask(da)
    assert w.values[0, 0] == 1 and w.values[0, 1] == 0 and w.values[1, 1] == 1
    assert np.isnan(w.values[1, 0])
    lin = da.copy(data=10 ** (data / 10))
    lin.attrs = {**da.attrs, "units": "linear"}
    np.testing.assert_array_equal(np.nan_to_num(ef.water_mask(lin).values, nan=-1),
                                  np.nan_to_num(w.values, nan=-1))


# ------------------------------------------------------------------- rivers

def _nhd(name, ftype, coords):
    return {"type": "Feature", "properties": {"gnis_name": name, "ftype": ftype},
            "geometry": {"type": "LineString", "coordinates": coords}}


@responses.activate
def test_river_centerline_prefers_long_named_river():
    from earthfetch.rivers import NHD_URL

    responses.add(responses.GET, NHD_URL, json={"type": "FeatureCollection",
        "features": [
            _nhd("Mill Creek", 460, [[0, 0], [0, 0.5]]),
            _nhd("Green River", 460, [[0, 0], [0.2, 0.1]]),
            _nhd("Green River", 558, [[0.2, 0.1], [0.3, 0.2]]),
            _nhd(None, 460, [[0, 0], [1, 1]]),
            _nhd("Big Ditch", 336, [[0, 0], [0.01, 0]]),
            _nhd("Some Shoreline", 999, [[0, 0], [5, 5]]),
        ]})
    feat = ef.river_centerline((-0.1, -0.1, 1, 1))
    # "River" names outrank a longer creek; unnamed lines never win
    assert feat["properties"] == {"name": "Green River", "source": "nhd"}
    assert len(feat["geometry"]["coordinates"]) == 2


@responses.activate
def test_river_centerline_by_name_and_missing_name():
    from earthfetch.rivers import NHD_URL

    for _ in range(2):
        responses.add(responses.GET, NHD_URL, json={"features": [
            _nhd("Mill Creek", 460, [[0, 0], [0, 0.5]]),
            _nhd("Green River", 460, [[0, 0], [0.2, 0.1]])]})
    assert ef.river_centerline((-0.1, -0.1, 1, 1), name="mill")[
        "properties"]["name"] == "Mill Creek"
    with pytest.raises(ef.EarthfetchError, match="no river named"):
        ef.river_centerline((-0.1, -0.1, 1, 1), name="Amazon")


@responses.activate
def test_river_centerline_falls_back_to_osm():
    from earthfetch.rivers import NHD_URL, OVERPASS_URL

    responses.add(responses.GET, NHD_URL, json={"error": {"code": 400}})
    responses.add(responses.POST, OVERPASS_URL, json={"elements": [
        {"type": "way", "tags": {"waterway": "river", "name": "Rhône"},
         "geometry": [{"lon": 6.0, "lat": 46.0}, {"lon": 6.1, "lat": 46.1}]}]})
    feat = ef.river_centerline((5.9, 45.9, 6.2, 46.2))
    assert feat["properties"] == {"name": "Rhône", "source": "osm"}


@responses.activate
def test_river_centerline_nothing_found():
    from earthfetch.rivers import NHD_URL, OVERPASS_URL

    responses.add(responses.GET, NHD_URL, json={"features": []})
    responses.add(responses.POST, OVERPASS_URL, json={"elements": []})
    with pytest.raises(ef.TileNotFoundError):
        ef.river_centerline((5.9, 45.9, 6.2, 46.2))


# ---------------------------------------------------------------------- REM

def _valley(h, w, transform):
    """Valley sloping 1 m/px down-valley (east) with walls rising 0.5 m per
    px away from a channel along the middle row."""
    rows, cols = np.mgrid[0:h, 0:w]
    return 100.0 - 0.1 * cols + 0.5 * np.abs(rows - h // 2)


def _mid_river(bbox=BBOX):
    lat = (bbox[1] + bbox[3]) / 2
    return {"type": "LineString",
            "coordinates": [[bbox[0], lat], [bbox[2], lat]]}


def test_rem_flattens_a_sloping_valley(tmp_path, monkeypatch):
    tif = _write(tmp_path / "dem.tif", _valley, 10.0)
    import earthfetch.usgs as usgs

    monkeypatch.setattr(usgs, "dem_tile_urls", lambda bbox, resolution: [str(tif)])
    import earthfetch.load as load

    monkeypatch.setattr(load, "dem_tile_urls", lambda bbox, resolution: [str(tif)])
    r = ef.rem(BBOX, river=_mid_river(), crs=CRS)
    assert set(r.data_vars) == {"rem", "dem", "water_surface", "hillshade"}
    h = r.rem.shape[0]
    mid = r.rem.values[h // 2, 5:-5]
    # on the channel the REM is ~0 even though the DEM drops along it
    assert np.nanmax(np.abs(mid)) < 1.0
    # the valley wall 10 px off-channel is ~5 m above the river everywhere
    wall = r.rem.values[h // 2 + 10, 5:-5]
    assert np.nanmedian(wall) == pytest.approx(5.0, abs=1.0)
    assert np.nanstd(wall) < 1.0      # the down-valley slope is removed
    assert r.attrs["river_source"] == "user"


def test_idw_matches_brute_force_reference():
    from earthfetch._rem import _idw

    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 100, (200, 2))
    z = xy[:, 0] * 0.3
    qx, qy = np.meshgrid(np.linspace(0, 100, 30), np.linspace(0, 100, 20))
    got = _idw(xy, z, qx, qy, k=8, power=2)
    q = np.column_stack([qx.ravel(), qy.ravel()])
    d = np.hypot(q[:, None, 0] - xy[None, :, 0], q[:, None, 1] - xy[None, :, 1])
    idx = np.argsort(d, axis=1)[:, :8]
    w = 1 / np.maximum(np.take_along_axis(d, idx, axis=1), 1e-6) ** 2
    want = ((w * z[idx]).sum(1) / w.sum(1)).reshape(qx.shape)
    np.testing.assert_allclose(got, want, rtol=1e-6)


def test_rem_river_outside_dem(tmp_path, monkeypatch):
    tif = _write(tmp_path / "dem.tif", _valley, 10.0)
    import earthfetch.load as load

    monkeypatch.setattr(load, "dem_tile_urls", lambda bbox, resolution: [str(tif)])
    far = {"type": "LineString", "coordinates": [[-100.0, 30.0], [-100.1, 30.1]]}
    with pytest.raises(ef.EarthfetchError, match="does not cross"):
        ef.rem(BBOX, river=far, crs=CRS)


def test_rem_rejects_non_line_river():
    from earthfetch._rem import _river_geometry

    poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    with pytest.raises(ef.EarthfetchError):
        _river_geometry(poly, ef.resolve_aoi(BBOX))


def test_rolling_median_removes_spike():
    from earthfetch._rem import _rolling_median

    z = np.arange(20, dtype=float)
    z[10] = 500.0   # a bridge deck
    out = _rolling_median(z, 7)
    assert out[10] == pytest.approx(10.0, abs=1.5)


# ------------------------------------------------------------------ preview

def test_preview_cmap_and_shade(tmp_path):
    pytest.importorskip("matplotlib")
    data = np.linspace(0, 10, 100, dtype="float32").reshape(10, 10)
    data[0, 0] = np.nan
    da = xr.DataArray(data, dims=("y", "x"), name="rem",
                      attrs={"crs": CRS, "transform": (10, 0, 0, 0, -10, 100)})
    out = ef.preview(da, tmp_path / "rem.png", cmap="YlGnBu_r", vmin=0, vmax=5,
                     shade=np.full((10, 10), 255.0))
    with rasterio.open(out) as png:
        img = png.read()
    assert img.shape == (3, 10, 10)
    assert tuple(img[:, 0, 0]) == (255, 255, 255)   # nodata is white
    assert not np.array_equal(img[0], img[2])        # it's colour, not grey
    with pytest.raises(ef.EarthfetchError):
        ef.preview(da, tmp_path / "bad.png", shade=np.ones((3, 3)))
