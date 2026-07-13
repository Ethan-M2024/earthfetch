"""Phase 3: Landsat Collection-2 L2 loader + composite source routing."""

from __future__ import annotations

import numpy as np
import pytest

import earthfetch as ef
from earthfetch.landsat import _resolve_band, scale_offset

xr = pytest.importorskip("xarray")
rasterio = pytest.importorskip("rasterio")

from earthfetch.raster import make_grid  # noqa: E402

BBOX = (-111.90, 40.70, -111.89, 40.708)
CRS = "EPSG:32612"


# ---- band resolution: friendly / Landsat / Sentinel names -> S2-equiv label ----

@pytest.mark.parametrize("band,asset,label", [
    ("red", "red", "B04"),
    ("B4", "red", "B04"),
    ("B04", "red", "B04"),
    ("nir", "nir08", "B08"),
    ("B5", "nir08", "B08"),
    ("swir1", "swir16", "B11"),
    ("green", "green", "B03"),
    ("blue", "blue", "B02"),
])
def test_band_resolution(band, asset, label):
    a, lbl = _resolve_band(band)
    assert a == asset and lbl == label


def test_unknown_band_raises():
    with pytest.raises(ef.BandNotFoundError):
        _resolve_band("purple")


def test_scale_offset_landsat_defaults():
    item = {"assets": {"red": {}}}
    sc, off = scale_offset(item, "red")
    assert sc == pytest.approx(2.75e-5)
    assert off == pytest.approx(-0.2)


def test_scale_offset_qa_identity():
    assert scale_offset({"assets": {"qa_pixel": {}}}, "qa") == (1.0, 0.0)


# ---- load_landsat against a local COG (network mocked) ----

def _landsat_item(tif):
    return {
        "id": "LC09_L2SP_test",
        "properties": {"datetime": "2024-07-01T18:00:00Z", "eo:cloud_cover": 3.0},
        "assets": {
            "red": {"href": str(tif),
                    "raster:bands": [{"scale": 2.75e-5, "offset": -0.2}]},
            "green": {"href": str(tif),
                      "raster:bands": [{"scale": 2.75e-5, "offset": -0.2}]},
            "blue": {"href": str(tif),
                     "raster:bands": [{"scale": 2.75e-5, "offset": -0.2}]},
        },
    }


def _write_dn(tmp_path, value=20000):
    transform, w, h = make_grid(BBOX, CRS, 30.0)
    tif = tmp_path / "ls.tif"
    with rasterio.open(tif, "w", driver="GTiff", width=w, height=h, count=1,
                       dtype="uint16", crs=CRS, transform=transform) as d:
        d.write(np.full((h, w), value, "uint16"), 1)
    return tif


def test_load_landsat_scales_and_labels(tmp_path, monkeypatch):
    tif = _write_dn(tmp_path, 20000)
    item = _landsat_item(tif)

    import earthfetch.landsat as lsmod
    # bypass the real MPC signing; the asset href is our local COG
    monkeypatch.setattr(lsmod, "sign_mpc", lambda href: href)

    da = ef.load_landsat(BBOX, bands="true_color", item=item, crs=CRS)
    # band labels normalized to Sentinel-2 equivalents so indices work
    assert list(da.band.values) == ["B04", "B03", "B02"]
    # 20000 * 2.75e-5 - 0.2 = 0.35 reflectance
    assert float(da.sel(band="B04").mean()) == pytest.approx(0.35, abs=1e-3)
    assert da.attrs["source"] == "landsat"


def test_ndvi_works_on_landsat_output(tmp_path, monkeypatch):
    # nir (B08) and red (B04) -> ndvi should resolve on the labeled output
    transform, w, h = make_grid(BBOX, CRS, 30.0)
    nir = tmp_path / "nir.tif"
    red = tmp_path / "red.tif"
    for path, val in [(nir, 30000), (red, 10000)]:
        with rasterio.open(path, "w", driver="GTiff", width=w, height=h,
                           count=1, dtype="uint16", crs=CRS,
                           transform=transform) as d:
            d.write(np.full((h, w), val, "uint16"), 1)
    item = {"id": "x", "properties": {"datetime": "2024-07-01T00:00:00Z"},
            "assets": {
                "nir08": {"href": str(nir),
                          "raster:bands": [{"scale": 2.75e-5, "offset": -0.2}]},
                "red": {"href": str(red),
                        "raster:bands": [{"scale": 2.75e-5, "offset": -0.2}]}}}
    import earthfetch.landsat as lsmod
    monkeypatch.setattr(lsmod, "sign_mpc", lambda href: href)

    da = ef.load_landsat(BBOX, bands=["nir", "red"], item=item, crs=CRS)
    ndvi = ef.ndvi(da)                       # finds B08/B04 labels
    assert -1 <= float(ndvi.mean()) <= 1
    assert float(ndvi.mean()) > 0.2          # veg-like (nir >> red)


# ---- composite source routing (unit-level, no network) ----

def test_composite_rejects_unknown_source():
    from earthfetch._composite import _source_adapter
    with pytest.raises(ValueError):
        _source_adapter("modis")


def test_composite_landsat_adapter_wires_landsat():
    from earthfetch._composite import _source_adapter
    search, url_of, scale_of, validity, native, label = _source_adapter("landsat")
    assert native(["B04"]) == 30.0
    assert label("red") == "B04"      # normalizes to S2-equivalent
    from earthfetch.landsat import search_landsat
    assert search is search_landsat


def test_public_landsat_symbols():
    assert callable(ef.search_landsat)
    assert "load_landsat" in ef.__all__ and "search_landsat" in ef.__all__
