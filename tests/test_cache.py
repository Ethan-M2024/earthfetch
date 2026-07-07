"""Cache management API: cache_dir, cache_info, clear_cache."""

from __future__ import annotations

import earthfetch as ef


def test_cache_dir_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("EARTHFETCH_CACHE", str(tmp_path / "ef"))
    assert ef.cache_dir() == tmp_path / "ef"


def test_cache_info_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("EARTHFETCH_CACHE", str(tmp_path / "empty"))
    info = ef.cache_info()
    assert info == {"path": str(tmp_path / "empty"), "files": 0, "bytes": 0}


def test_cache_info_and_clear_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("EARTHFETCH_CACHE", str(tmp_path / "c"))
    root = ef.cache_dir()
    (root / "downloads").mkdir(parents=True)
    (root / "downloads" / "a.tif").write_bytes(b"x" * 1000)
    (root / "downloads" / "b.tif").write_bytes(b"y" * 500)

    info = ef.cache_info()
    assert info["files"] == 2
    assert info["bytes"] == 1500

    freed = ef.clear_cache()
    assert freed == 1500
    assert not root.exists()
    assert ef.cache_info()["files"] == 0


def test_clear_cache_missing_dir_is_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("EARTHFETCH_CACHE", str(tmp_path / "nope"))
    assert ef.clear_cache() == 0


def test_http_retries_env_read(monkeypatch):
    import earthfetch.utils as u
    monkeypatch.setattr(u, "_session", None)
    monkeypatch.setenv("EARTHFETCH_HTTP_RETRIES", "7")
    s = u.get_session()
    retry = s.get_adapter("https://x").max_retries
    assert retry.total == 7


def test_gdal_env_has_retries():
    from earthfetch.raster import _ENV
    assert "GDAL_HTTP_MAX_RETRY" in _ENV
    assert "GDAL_HTTP_RETRY_DELAY" in _ENV


def test_cache_functions_public():
    for name in ("cache_dir", "cache_info", "clear_cache"):
        assert name in ef.__all__
