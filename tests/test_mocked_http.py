"""HTTP-mocked tests — run in CI with no network."""


import pytest
import responses

import earthfetch.utils
from earthfetch.exceptions import DownloadError
from earthfetch.sentinel import STAC_URL, search_sentinel2
from earthfetch.usgs import TNM_URL, dem_tile_urls, search_dem
from earthfetch.utils import download_file


@pytest.fixture(autouse=True)
def fresh_session(monkeypatch):
    # responses can't see a session created before activation; reset the pool
    monkeypatch.setattr(earthfetch.utils, "_session", None)


def _tnm_item(title, url, date="2022-05-10"):
    return {
        "title": title,
        "downloadURL": url,
        "sizeInBytes": 1000,
        "publicationDate": date,
    }


@responses.activate
def test_search_dem_paginates():
    page1 = {
        "total": 3,
        "items": [
            _tnm_item("USGS 1/3 Arc Second n41w112 20211101", "https://x/a.tif"),
            _tnm_item("USGS 1/3 Arc Second n41w113 20211101", "https://x/b.tif"),
        ],
    }
    page2 = {
        "total": 3,
        "items": [_tnm_item("USGS 1/3 Arc Second n42w112 20211101", "https://x/c.tif")],
    }
    responses.add(responses.GET, TNM_URL, json=page1)
    responses.add(responses.GET, TNM_URL, json=page2)
    items = search_dem((-113, 40, -111, 42), "10m")
    assert len(items) == 3


@responses.activate
def test_dem_tile_urls_dedupes_republished_tiles():
    body = {
        "total": 3,
        "items": [
            _tnm_item("USGS 1/3 Arc Second n41w112 20211101",
                      "https://x/old.tif", "2021-11-01"),
            _tnm_item("USGS 1/3 Arc Second n41w112 20220510",
                      "https://x/new.tif", "2022-05-10"),
            _tnm_item("USGS 1/3 Arc Second n41w113 20211101",
                      "https://x/other.tif", "2021-11-01"),
        ],
    }
    responses.add(responses.GET, TNM_URL, json=body)
    urls = dem_tile_urls((-113, 40, -111, 41), "10m")
    assert sorted(urls) == ["https://x/new.tif", "https://x/other.tif"]


@responses.activate
def test_search_sentinel2_sorts_by_cloud():
    def feature(sid, cloud):
        return {"id": sid, "properties": {"eo:cloud_cover": cloud}, "assets": {}}

    body = {
        "features": [feature("cloudy", 15.0), feature("clear", 2.0)],
        "links": [],
    }
    responses.add(responses.POST, STAC_URL, json=body)
    items = search_sentinel2((-112, 40, -111, 41), "2026-05-01", "2026-06-01")
    assert [i["id"] for i in items] == ["clear", "cloudy"]


@responses.activate
def test_download_verifies_length(tmp_path):
    responses.add(
        responses.GET, "https://x/file.bin", body=b"abc",
        headers={"Content-Length": "999"},
    )
    with pytest.raises(DownloadError):
        download_file("https://x/file.bin", out_dir=tmp_path)
    assert not (tmp_path / "file.bin").exists()
    assert not (tmp_path / "file.bin.part").exists()


@responses.activate
def test_download_skips_existing(tmp_path):
    (tmp_path / "file.bin").write_bytes(b"cached")
    path = download_file("https://x/file.bin", out_dir=tmp_path)
    assert path.read_bytes() == b"cached"
    assert len(responses.calls) == 0
