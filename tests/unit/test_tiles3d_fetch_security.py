"""The untrusted-asset policy as it applies to a 3D Tiles tileset.

A ``tileset.json`` names its tile payloads, and its nested tilesets, by URI. For
a tileset from an untrusted source those URIs are attacker-controlled, so they go
through the same containment as a glTF document's external references
(:mod:`OpenGLContext.loaders.resolver`): a tileset fetched over http(s) may pull
only same-origin http(s) references, one loaded from disk may read only files
under its own directory, and every payload is size-capped.

The root tileset the *user* named is a different thing and stays unrestricted --
that URI came from the command line, not from a document.
"""
import os

import pytest

from OpenGLContext.loaders import resolver
from OpenGLContext.loaders.tiles3d import fetch


REMOTE = "https://tiles.example.invalid/city/"


class TestAReferenceFromARemoteTileset:
    """A tileset served over http(s) may only reach its own origin."""

    def test_an_absolute_path_stays_on_the_origin_and_never_becomes_a_file(self):
        # A leading slash is root-relative *on this server*, as it is in a
        # browser -- so it must come back a same-origin URL. Returning it
        # unchanged would hand read_bytes something with no scheme, which it
        # would open off the local disk.
        resolved = fetch.resolve_uri(REMOTE, "/etc/passwd")
        assert resolved == "https://tiles.example.invalid/etc/passwd"
        assert fetch.is_url(resolved)

    def test_another_host_is_refused(self):
        # Unrestricted SSRF, including link-local metadata endpoints.
        with pytest.raises(IOError):
            fetch.resolve_uri(REMOTE, "http://169.254.169.254/latest/meta-data/")

    def test_the_same_host_on_another_port_is_refused(self):
        with pytest.raises(IOError):
            fetch.resolve_uri(REMOTE, "https://tiles.example.invalid:8080/x.glb")

    def test_a_file_uri_is_refused(self):
        with pytest.raises(IOError):
            fetch.resolve_uri(REMOTE, "file:///etc/passwd")

    def test_a_relative_reference_resolves_against_the_tileset(self):
        assert fetch.resolve_uri(REMOTE, "tiles/0/0.glb") == (
            "https://tiles.example.invalid/city/tiles/0/0.glb")

    def test_a_reference_above_the_tileset_stays_on_the_origin(self):
        # Same-origin is the whole policy for a URL; a parent path is still the
        # same server and is allowed, exactly as it is for a glTF document.
        assert fetch.resolve_uri(REMOTE, "../shared/tree.glb") == (
            "https://tiles.example.invalid/shared/tree.glb")


class TestAReferenceFromALocalTileset:
    """A tileset loaded from disk may only read files under its own directory."""

    def test_traversal_above_the_tileset_is_refused(self, tmp_path):
        with pytest.raises(IOError):
            fetch.resolve_uri(str(tmp_path), "../../../etc/shadow")

    def test_an_absolute_path_is_refused(self, tmp_path):
        with pytest.raises(IOError):
            fetch.resolve_uri(str(tmp_path), "/etc/passwd")

    def test_a_url_is_refused(self, tmp_path):
        with pytest.raises(IOError):
            fetch.resolve_uri(str(tmp_path), "http://169.254.169.254/")

    def test_a_child_file_resolves(self, tmp_path):
        (tmp_path / "tiles").mkdir()
        assert fetch.resolve_uri(str(tmp_path), "tiles/0.glb") == str(
            tmp_path / "tiles" / "0.glb")

    def test_a_symlink_out_of_the_tileset_is_refused(self, tmp_path):
        outside = tmp_path.parent / "outside.glb"
        outside.write_bytes(b"x")
        base = tmp_path / "set"
        base.mkdir()
        try:
            os.symlink(outside, base / "link.glb")
        except (OSError, NotImplementedError):        # pragma: no cover
            pytest.skip("symlinks unavailable")
        with pytest.raises(IOError):
            fetch.resolve_uri(str(base), "link.glb")


class TestTheRootTilesetTheUserNamed:
    """No base means the user typed it; it is not a document's reference."""

    def test_an_absolute_local_path_is_kept(self, tmp_path):
        assert fetch.resolve_uri("", str(tmp_path / "t.json")) == str(
            tmp_path / "t.json")

    def test_a_url_is_kept(self):
        assert fetch.resolve_uri("", REMOTE + "tileset.json") == (
            REMOTE + "tileset.json")


class TestReadBytesIsSizeCapped:
    """A payload is bounded, so one hostile tile cannot exhaust memory."""

    def test_a_local_file_over_the_cap_is_refused(self, tmp_path):
        path = tmp_path / "big.glb"
        path.write_bytes(b"x" * 4096)
        with pytest.raises(ValueError):
            fetch.read_bytes(str(path), max_bytes=1024)

    def test_a_local_file_under_the_cap_is_read(self, tmp_path):
        path = tmp_path / "small.glb"
        path.write_bytes(b"abc")
        assert fetch.read_bytes(str(path), max_bytes=1024) == b"abc"

    def test_a_remote_payload_goes_through_the_capped_fetch(self, tmp_path, monkeypatch):
        seen = {}

        def fake(url, cache_dir=None, max_bytes=None, **kw):
            seen.update(url=url, cache_dir=cache_dir, max_bytes=max_bytes)
            return b"glb"

        monkeypatch.setattr(resolver, "_fetch_url", fake)
        got = fetch.read_bytes(REMOTE + "0.glb", cache_dir=str(tmp_path),
                               max_bytes=99)
        assert got == b"glb"
        assert seen["url"] == REMOTE + "0.glb"
        assert seen["max_bytes"] == 99


class _FakeResponse:
    """Just enough of an http response for the resolver's streaming reader."""

    def __init__(self, payload: bytes) -> None:
        self._rest = payload
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int) -> bytes:
        chunk, self._rest = self._rest[:size], self._rest[size:]
        return chunk

    def close(self) -> None:
        pass


class TestTheCacheTheTilesRuntimeUses:
    """The tile cache is the resolver's, with the guarantees that carries."""

    def test_the_cache_directory_is_not_world_readable(self, tmp_path, monkeypatch):
        # Another account must not be able to pre-seed a tile this user loads.
        monkeypatch.setattr(resolver, "_urlopen_same_origin",
                            lambda url, base, timeout=30: _FakeResponse(b"glb"))
        cache = tmp_path / "tiles3d"
        assert fetch.read_bytes(REMOTE + "0.glb", cache_dir=str(cache)) == b"glb"
        assert (os.stat(cache).st_mode & 0o077) == 0

    def test_a_second_read_of_one_tile_does_not_refetch(self, tmp_path, monkeypatch):
        calls = []

        def once(url, base, timeout=30):
            calls.append(url)
            return _FakeResponse(b"glb")

        monkeypatch.setattr(resolver, "_urlopen_same_origin", once)
        for _ in range(2):
            fetch.read_bytes(REMOTE + "0.glb", cache_dir=str(tmp_path))
        assert len(calls) == 1

    def test_a_remote_payload_over_the_cap_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(resolver, "_urlopen_same_origin",
                            lambda url, base, timeout=30: _FakeResponse(b"x" * 4096))
        with pytest.raises(ValueError):
            fetch.read_bytes(REMOTE + "0.glb", cache_dir=str(tmp_path),
                             max_bytes=1024)
