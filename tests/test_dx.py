"""Offline tests for the DX helpers: band presets, normalized_difference,
show(), and elevation()."""

from __future__ import annotations

import numpy as np
import pytest

import earthfetch as ef
from earthfetch.sentinel import BAND_PRESETS, resolve_bands

xr = pytest.importorskip("xarray")


# --------------------------------------------------------------------------
# band presets
# --------------------------------------------------------------------------

@pytest.mark.parametrize("preset,first", [
    ("true_color", "B04"),
    ("false_color", "B08"),
    ("color_infrared", "B08"),
    ("agriculture", "B11"),
    ("swir", "B12"),
    ("geology", "B12"),
    ("healthy_vegetation", "B08"),
])
def test_preset_expands(preset, first):
    out = resolve_bands(preset)
    assert out == list(BAND_PRESETS[preset])
    assert out[0] == first
    assert len(out) == 3


def test_resolve_bands_single_id():
    assert resolve_bands("B08") == ["B08"]   # not split into characters


def test_resolve_bands_sequence_passthrough():
    assert resolve_bands(["B04", "B08"]) == ["B04", "B08"]


def test_preset_case_insensitive():
    assert resolve_bands("True_Color") == ["B04", "B03", "B02"]


def test_band_presets_exported():
    assert "BAND_PRESETS" in ef.__all__
    assert ef.BAND_PRESETS["true_color"] == ("B04", "B03", "B02")


# --------------------------------------------------------------------------
# normalized_difference
# --------------------------------------------------------------------------

def _ds():
    def mk(v):
        return xr.DataArray(np.full((3, 3), v, "float32"), dims=("y", "x"))
    return xr.Dataset({"B03": mk(0.2), "B08": mk(0.5), "B04": mk(0.1)})


def test_normalized_difference_matches_ndvi():
    ds = _ds()
    nd = ef.normalized_difference(ds, "B08", "B04", name="ndvi")
    assert float(nd.mean()) == pytest.approx(float(ef.ndvi(ds).mean()))
    assert nd.name == "ndvi"


def test_normalized_difference_custom_name_default():
    nd = ef.normalized_difference(_ds(), "B03", "B08")
    assert nd.name == "nd"
    assert float(nd.mean()) == pytest.approx((0.2 - 0.5) / (0.2 + 0.5))


def test_normalized_difference_missing_band():
    with pytest.raises(ef.BandNotFoundError):
        ef.normalized_difference(_ds(), "B08", "B12")


# --------------------------------------------------------------------------
# show()
# --------------------------------------------------------------------------

def _geo_da(nbands):
    from earthfetch.load import _to_dataarray
    from earthfetch.raster import make_grid
    crs = "EPSG:32612"
    transform, w, h = make_grid((-111.9, 40.70, -111.89, 40.708), crs, 10.0)
    if nbands == 1:
        data = np.random.default_rng(0).random((h, w)).astype("float32")
        return _to_dataarray(data, transform, w, h, crs, "ndvi", {})
    data = np.random.default_rng(0).random((nbands, h, w)).astype("float32")
    da = _to_dataarray(data, transform, w, h, crs, "img", {})
    return da.assign_coords(band=("band", ["B04", "B03", "B02"][:nbands]))


def test_show_rgb_returns_axes():
    pytest.importorskip("matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    ax = ef.show(_geo_da(3))
    assert ax.images or ax.get_images()
    import matplotlib.pyplot as plt
    plt.close("all")


def test_show_single_band_has_colorbar():
    pytest.importorskip("matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ax = ef.show(_geo_da(1))
    # a colorbar adds a second Axes to the figure
    assert len(ax.figure.axes) == 2
    plt.close("all")


def test_show_accepts_existing_ax():
    pytest.importorskip("matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    out = ef.show(_geo_da(3), ax=ax, colorbar=False)
    assert out is ax
    plt.close("all")


# --------------------------------------------------------------------------
# elevation() — DEM loading mocked, sampling exercised for real
# --------------------------------------------------------------------------

def test_elevation_single_point(monkeypatch):
    from earthfetch.load import _to_dataarray
    from earthfetch.raster import make_grid

    crs = "EPSG:32612"
    bbox = (-111.9, 40.70, -111.89, 40.708)
    transform, w, h = make_grid(bbox, crs, 10.0)
    dem = _to_dataarray(np.full((h, w), 1500.0, "float32"),
                        transform, w, h, crs, "dem", {})

    import earthfetch.load as loadmod
    monkeypatch.setattr(loadmod, "load_dem", lambda *a, **k: dem)

    val = ef.elevation((-111.895, 40.704))
    assert isinstance(val, float)
    assert val == pytest.approx(1500.0)


def test_elevation_multiple_points_returns_array(monkeypatch):
    from earthfetch.load import _to_dataarray
    from earthfetch.raster import make_grid

    crs = "EPSG:32612"
    bbox = (-111.9, 40.70, -111.89, 40.708)
    transform, w, h = make_grid(bbox, crs, 10.0)
    dem = _to_dataarray(np.full((h, w), 1500.0, "float32"),
                        transform, w, h, crs, "dem", {})

    import earthfetch.load as loadmod
    monkeypatch.setattr(loadmod, "load_dem", lambda *a, **k: dem)

    out = ef.elevation([(-111.895, 40.704), (-111.892, 40.706)])
    assert out.shape == (2,)
    assert np.allclose(out, 1500.0)
