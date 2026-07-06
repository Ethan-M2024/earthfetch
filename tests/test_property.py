"""Property-based tests (Hypothesis) for the geometry / bbox / index math.

These assert invariants that must hold for *all* valid inputs, not just
the hand-picked cases in the example-based suites — the class of edge case
that hand-written tests routinely miss.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from earthfetch.aoi import _pad_degenerate, resolve_aoi, utm_crs
from earthfetch.copernicus import _tile_name
from earthfetch.indices import INDICES
from earthfetch.utils import validate_bbox

xr = pytest.importorskip("xarray")


# ---- bbox strategies -----------------------------------------------------

def _finite(lo, hi):
    return st.floats(min_value=lo, max_value=hi, allow_nan=False,
                     allow_infinity=False)


@st.composite
def bboxes(draw):
    """A valid (min_lon, min_lat, max_lon, max_lat) in WGS84."""
    min_lon = draw(_finite(-180.0, 179.0))
    max_lon = draw(_finite(min_lon + 1e-3, 180.0))
    min_lat = draw(_finite(-90.0, 89.0))
    max_lat = draw(_finite(min_lat + 1e-3, 90.0))
    return (min_lon, min_lat, max_lon, max_lat)


# ---- validate_bbox -------------------------------------------------------

@given(bboxes())
def test_validate_bbox_roundtrips(bbox):
    out = validate_bbox(bbox)
    assert out == pytest.approx(bbox)
    assert all(isinstance(v, float) for v in out)


@given(bboxes())
def test_validate_bbox_is_idempotent(bbox):
    once = validate_bbox(bbox)
    assert validate_bbox(once) == once


# ---- utm_crs -------------------------------------------------------------

@given(bboxes())
def test_utm_crs_always_valid_zone(bbox):
    code = utm_crs(bbox)
    assert code.startswith("EPSG:")
    num = int(code.split(":")[1])
    band, zone = divmod(num, 100)
    assert band in (326, 327)          # north / south
    assert 1 <= zone <= 60


@given(bboxes())
def test_utm_hemisphere_matches_center_latitude(bbox):
    _, min_lat, _, max_lat = bbox
    center = (min_lat + max_lat) / 2
    code = utm_crs(bbox)
    assert code.startswith("EPSG:326" if center >= 0 else "EPSG:327")


@given(
    lon_a=_finite(-179.0, 179.0),
    lon_b=_finite(-179.0, 179.0),
    lat=_finite(-80.0, 80.0),
)
def test_utm_zone_monotonic_in_longitude(lon_a, lon_b, lat):
    assume(abs(lon_a - lon_b) > 1e-6)
    lo, hi = sorted((lon_a, lon_b))
    box_lo = (lo - 1e-4, lat, lo + 1e-4, lat + 1e-3)
    box_hi = (hi - 1e-4, lat, hi + 1e-4, lat + 1e-3)
    zone_lo = int(utm_crs(box_lo).split(":")[1]) % 100
    zone_hi = int(utm_crs(box_hi).split(":")[1]) % 100
    assert zone_lo <= zone_hi


# ---- _pad_degenerate -----------------------------------------------------

@given(
    x=_finite(-180.0, 180.0),
    y=_finite(-90.0, 90.0),
    dx=st.floats(0.0, 5.0, allow_nan=False),
    dy=st.floats(0.0, 5.0, allow_nan=False),
)
def test_pad_degenerate_always_strictly_ordered(x, y, dx, dy):
    minx, miny, maxx, maxy = _pad_degenerate(x, y, x + dx, y + dy)
    assert minx < maxx
    assert miny < maxy


@given(x=_finite(-180.0, 180.0), y=_finite(-90.0, 90.0))
def test_pad_degenerate_contains_original_point(x, y):
    minx, miny, maxx, maxy = _pad_degenerate(x, y, x, y)
    assert minx < x < maxx
    assert miny < y < maxy


# ---- resolve_aoi ---------------------------------------------------------

@given(bboxes())
def test_resolve_aoi_preserves_bbox(bbox):
    aoi = resolve_aoi(bbox)
    assert aoi.bbox == pytest.approx(validate_bbox(bbox))
    assert aoi.geometry is None


# ---- Copernicus tile naming ----------------------------------------------

@given(
    lat=st.integers(-90, 89),
    lon=st.integers(-180, 179),
)
def test_tile_name_encodes_hemisphere_and_magnitude(lat, lon):
    name = _tile_name(lat, lon)
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    assert f"_{ns}{abs(lat):02d}_00_" in name
    assert f"_{ew}{abs(lon):03d}_00_" in name
    assert name.startswith("Copernicus_DSM_COG_10_")
    assert name.endswith("_DEM")


# ---- normalized-difference indices are bounded ---------------------------

ND_INDICES = ["ndvi", "ndwi", "nbr", "ndmi", "ndsi", "ndre", "ndbi",
              "gndvi", "bsi"]

_reflectance = st.floats(1e-4, 1.0, allow_nan=False, allow_infinity=False)


@pytest.mark.parametrize("name", ND_INDICES)
@given(vals=st.lists(_reflectance, min_size=7, max_size=7))
def test_nd_index_bounded(name, vals):
    bands = ["B02", "B03", "B04", "B05", "B08", "B11", "B12"]
    ds = xr.Dataset({
        b: xr.DataArray(np.full((2, 2), v, "float32"), dims=("y", "x"))
        for b, v in zip(bands, vals)
    })
    out = INDICES[name](ds).values
    assert np.all(np.isfinite(out))
    assert np.all(out >= -1.0 - 1e-6)
    assert np.all(out <= 1.0 + 1e-6)
