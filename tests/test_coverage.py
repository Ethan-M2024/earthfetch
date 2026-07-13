"""Phase 1: greedy-fill scene coverage (covering_scenes + multi-item load)."""

from __future__ import annotations

import pytest
import responses

import earthfetch as ef
import earthfetch.utils
from earthfetch.sentinel import STAC_URL, _covers_point, covering_scenes


@pytest.fixture(autouse=True)
def _fresh_session(monkeypatch):
    monkeypatch.setattr(earthfetch.utils, "_session", None)


# ---- point-in-polygon primitive ----

def _square(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[
        [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def test_covers_point_inside_and_outside():
    sq = _square(0, 0, 10, 10)
    assert _covers_point(sq, 5, 5) is True
    assert _covers_point(sq, 15, 5) is False
    assert _covers_point(sq, -1, -1) is False


def test_covers_point_multipolygon():
    mp = {"type": "MultiPolygon", "coordinates": [
        _square(0, 0, 1, 1)["coordinates"],
        _square(5, 5, 6, 6)["coordinates"],
    ]}
    assert _covers_point(mp, 0.5, 0.5) is True
    assert _covers_point(mp, 5.5, 5.5) is True
    assert _covers_point(mp, 3, 3) is False


def test_covers_point_respects_holes():
    poly = {"type": "Polygon", "coordinates": [
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],   # exterior
        [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],       # hole
    ]}
    assert _covers_point(poly, 1, 1) is True
    assert _covers_point(poly, 5, 5) is False   # inside the hole


# ---- greedy set-cover (HTTP-mocked search) ----

def _scene(sid, cloud, geom, date="2024-06-01"):
    return {"id": sid, "geometry": geom,
            "properties": {"eo:cloud_cover": cloud,
                           "datetime": f"{date}T00:00:00Z"},
            "assets": {}}


@responses.activate
def test_covering_scenes_picks_minimal_set():
    # bbox 0..10 x 0..10; a left scene and a right scene each cover half.
    # A cloudier scene covers everything but should be skipped once the two
    # clear halves already cover the bbox.
    body = {"features": [
        _scene("left", 2, _square(-1, -1, 5.5, 11)),
        _scene("right", 3, _square(4.5, -1, 11, 11)),
        _scene("cloudy_full", 40, _square(-1, -1, 11, 11)),
    ], "links": []}
    responses.add(responses.POST, STAC_URL, json=body)
    scenes = covering_scenes((0, 0, 10, 10), "2024-06-01", "2024-07-01",
                             max_cloud=50)
    ids = {s["id"] for s in scenes}
    assert ids == {"left", "right"}      # two clear halves, not the cloudy one


@responses.activate
def test_covering_scenes_single_when_one_covers():
    body = {"features": [
        _scene("full", 1, _square(-1, -1, 11, 11)),
        _scene("half", 0, _square(-1, -1, 5, 11)),
    ], "links": []}
    responses.add(responses.POST, STAC_URL, json=body)
    scenes = covering_scenes((0, 0, 10, 10), "2024-06-01", "2024-07-01")
    # the clearest (half, cloud 0) is picked first, then full completes cover
    assert "full" in {s["id"] for s in scenes}


@responses.activate
def test_covering_scenes_no_scenes_raises():
    responses.add(responses.POST, STAC_URL, json={"features": [], "links": []})
    with pytest.raises(ef.NoScenesError):
        covering_scenes((0, 0, 10, 10), "2024-06-01", "2024-07-01")


@responses.activate
def test_covering_scenes_partial_cover_warns(caplog):
    # only a left scene exists; the right half stays uncovered
    body = {"features": [_scene("left", 1, _square(-1, -1, 5, 11))],
            "links": []}
    responses.add(responses.POST, STAC_URL, json=body)
    import logging
    with caplog.at_level(logging.WARNING, logger="earthfetch"):
        scenes = covering_scenes((0, 0, 10, 10), "2024-06-01", "2024-07-01")
    assert scenes[0]["id"] == "left"
    assert any("uncovered" in r.message for r in caplog.records)


def test_covering_scenes_exported():
    assert "covering_scenes" in ef.__all__
    assert callable(ef.covering_scenes)
