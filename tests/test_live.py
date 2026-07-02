"""Live-API tests — deselect with ``pytest -m "not network"``."""

import numpy as np
import pytest

pytestmark = pytest.mark.network

BBOX = (-111.90, 40.70, -111.88, 40.72)  # tiny: Salt Lake City


def test_search_dem_live():
    from earthfetch import search_dem

    tiles = search_dem(BBOX, resolution="10m", max_items=5)
    assert tiles and all("downloadURL" in t for t in tiles)


def test_search_sentinel2_live():
    from earthfetch import search_sentinel2

    items = search_sentinel2(BBOX, "2026-05-01", "2026-06-01", max_cloud=50)
    assert items
    clouds = [i["properties"]["eo:cloud_cover"] for i in items]
    assert clouds == sorted(clouds)


def test_load_dem_windowed_usgs():
    from earthfetch import load_dem

    da = load_dem(BBOX, resolution="10m", crs="EPSG:32612")
    assert da.dims == ("y", "x")
    assert da.attrs["source"] == "usgs"
    vals = da.values[np.isfinite(da.values)]
    assert 1200 < vals.mean() < 1600  # Salt Lake valley elevation


def test_load_dem_copernicus_global():
    from earthfetch import load_dem

    # Mont Blanc — outside the US, exercises the Copernicus fallback
    da = load_dem((6.85, 45.82, 6.88, 45.85), crs="EPSG:32632", source="copernicus")
    assert da.attrs["source"] == "copernicus"
    vals = da.values[np.isfinite(da.values)]
    assert vals.max() > 4000


def test_stack_aligned():
    from earthfetch import stack

    ds = stack(BBOX, crs="EPSG:32612", res=60, bands=["B04", "B08"],
               start="2026-05-01", end="2026-06-01")
    assert set(ds.data_vars) == {"dem", "B04", "B08"}
    assert ds.dem.shape == ds.B04.shape == ds.B08.shape
    ndvi = (ds.B08 - ds.B04) / (ds.B08 + ds.B04)
    assert np.isfinite(ndvi.values).any()


def test_composite_place_name_live():
    import earthfetch as ef

    da = ef.composite("Moab, Utah", bands=["B04"], res=60,
                      start="2026-05-01", end="2026-06-01", max_scenes=2)
    assert da.attrs["crs"] == "EPSG:32612"
    assert da.attrs["aoi_name"]  # geocoded
    assert np.isfinite(da.values).any()


def test_terrain_live():
    import earthfetch as ef

    ds = ef.terrain(BBOX, products=["dem", "slope"], resolution="30m")
    assert float(ds.slope.max()) > 0
    assert ds.attrs["crs"] == "EPSG:32612"  # auto-UTM


def test_load_naip_live():
    import earthfetch as ef

    img = ef.load_naip(BBOX, res=10)
    assert img.shape[0] == 3
    assert img.attrs["source"] == "naip"
    assert np.isfinite(img.values).mean() > 0.95  # full rect, no fragment
