"""URI resolution and reading for local and remote tilesets.

Covers scheme-aware base/relative joins, local reads, and remote reads with the disk
cache (network mocked so the suite stays offline/CI-safe).
"""
import os

import pytest

from OpenGLContext.loaders.tiles3d import fetch


def test_is_url_distinguishes_urls_from_paths():
    assert fetch.is_url("https://host/a/tileset.json")
    assert fetch.is_url("http://host/a")
    assert not fetch.is_url("/local/path/tileset.json")
    assert not fetch.is_url("relative/tile.b3dm")


def test_resolve_uri_joins_urls():
    base = "https://host.example/tiles/1.0/set/"
    assert fetch.resolve_uri(base, "dragon_low.b3dm") == \
        "https://host.example/tiles/1.0/set/dragon_low.b3dm"
    # A nested "../" resolves as a URL, not a filesystem join.
    assert fetch.resolve_uri(base, "../other/x.glb") == \
        "https://host.example/tiles/1.0/other/x.glb"


def test_resolve_uri_joins_local_paths():
    assert fetch.resolve_uri("/data/set/", "tile.b3dm") == "/data/set/tile.b3dm"


def test_resolve_uri_confines_a_local_tileset_to_its_own_directory():
    """A local tileset names files under itself, and nothing else: neither an
    absolute path nor a URL, both of which would reach outside the dataset."""
    with pytest.raises(IOError):
        fetch.resolve_uri("/data/set/", "/abs/tile.b3dm")
    with pytest.raises(IOError):
        fetch.resolve_uri("/data/set/", "https://h/x.glb")


def test_dir_of_url_and_path():
    assert fetch.dir_of("https://h/a/b/tileset.json") == "https://h/a/b/"
    assert fetch.dir_of("/a/b/tileset.json") == "/a/b" + os.sep


def test_read_bytes_local(tmp_path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"hello-tile")
    assert fetch.read_bytes(str(p)) == b"hello-tile"


def test_read_bytes_url_caches_and_reuses(tmp_path, monkeypatch):
    calls = {"n": 0}

    class _Resp:
        """Just enough of an http response for the streaming reader."""

        headers: dict = {}

        def __init__(self, data):
            self._data = data

        def read(self, size=-1):
            data, self._data = self._data, b""
            return data if size < 0 else data[:size]

        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_open(url, base_url, timeout=None):
        calls["n"] += 1
        return _Resp(b"remote-bytes")

    # read_bytes fetches through the resolver's cache, so the stub goes at the
    # one call that reaches the network -- leaving the caching itself real,
    # which is what this test is about.
    from OpenGLContext.loaders import resolver
    monkeypatch.setattr(resolver, "_urlopen_same_origin", fake_open)
    cache = str(tmp_path / "cache")
    url = "https://host.example/set/tile.b3dm"

    assert fetch.read_bytes(url, cache_dir=cache) == b"remote-bytes"
    assert fetch.read_bytes(url, cache_dir=cache) == b"remote-bytes"
    assert calls["n"] == 1                     # second read served from cache
    # The cache file exists and holds the payload.
    files = os.listdir(cache)
    assert len(files) == 1
