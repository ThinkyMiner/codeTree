import pytest
from codetree.cache import Cache


def test_cache_write_and_read(tmp_path):
    cache = Cache(tmp_path)
    data = {"mtime": 1234.0, "skeleton": [{"name": "foo", "type": "function", "line": 1}]}
    cache.set("src/foo.py", data)
    cache.save()

    cache2 = Cache(tmp_path)
    cache2.load()
    assert cache2.get("src/foo.py") == data


def test_cache_returns_none_for_missing_key(tmp_path):
    cache = Cache(tmp_path)
    cache.load()
    assert cache.get("nonexistent.py") is None


def test_cache_is_valid_when_mtime_matches(tmp_path):
    cache = Cache(tmp_path)
    cache.set("src/foo.py", {"mtime": 999.0, "skeleton": []})
    assert cache.is_valid("src/foo.py", 999.0) is True


def test_cache_is_invalid_when_mtime_differs(tmp_path):
    cache = Cache(tmp_path)
    cache.set("src/foo.py", {"mtime": 999.0, "skeleton": []})
    assert cache.is_valid("src/foo.py", 1000.0) is False


def test_cache_creates_directory_if_missing(tmp_path):
    cache_dir = tmp_path / ".codetree"
    assert not cache_dir.exists()
    cache = Cache(tmp_path)
    cache.save()
    assert cache_dir.exists()


def test_cache_file_is_world_readable_like_before(tmp_path):
    import os
    import stat
    from codetree.cache import Cache

    cache = Cache(tmp_path)
    cache.set("a.py", {"mtime": 1.0, "skeleton": []})
    cache.save()
    cache_file = tmp_path / ".codetree" / "index.json"
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o644

    os.chmod(cache_file, 0o600)  # a user's explicit choice is kept
    cache.save()
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600
