import pytest

from earthfetch.copernicus import _tile_name
from earthfetch.exceptions import BandNotFoundError
from earthfetch.sentinel import _asset_key, band_url, scene_summary
from earthfetch.utils import validate_bbox


def test_validate_bbox_ok():
    assert validate_bbox([-111.9, 40.7, -111.8, 40.8]) == (-111.9, 40.7, -111.8, 40.8)


@pytest.mark.parametrize(
    "bad",
    [
        [0, 0, 0],  # wrong length
        [-111.8, 40.7, -111.9, 40.8],  # min_lon > max_lon
        [-111.9, 40.8, -111.8, 40.7],  # min_lat > max_lat
        [-181, 40.7, -111.8, 40.8],  # out of range
    ],
)
def test_validate_bbox_rejects(bad):
    with pytest.raises(ValueError):
        validate_bbox(bad)


def test_band_aliases():
    assert _asset_key("B04") == "red"
    assert _asset_key("b08") == "nir"
    assert _asset_key("TCI") == "visual"
    assert _asset_key("red") == "red"  # passthrough for asset keys


def test_band_url_missing_raises():
    item = {"id": "X", "assets": {"red": {"href": "https://x/red.tif"}}}
    assert band_url(item, "B04") == "https://x/red.tif"
    with pytest.raises(BandNotFoundError):
        band_url(item, "B08")


def test_copernicus_tile_names():
    assert _tile_name(40, -112) == "Copernicus_DSM_COG_10_N40_00_W112_00_DEM"
    assert _tile_name(-2, 30) == "Copernicus_DSM_COG_10_S02_00_E030_00_DEM"


def test_scene_summary():
    item = {
        "id": "S2A_TEST",
        "properties": {
            "datetime": "2026-05-14T18:19:21Z",
            "eo:cloud_cover": 3.14159,
            "grid:code": "MGRS-12TVL",
        },
    }
    s = scene_summary(item)
    assert s == {
        "id": "S2A_TEST",
        "date": "2026-05-14",
        "cloud_pct": 3.1,
        "tile": "MGRS-12TVL",
    }
