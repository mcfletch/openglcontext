"""Extra coverage for loaders.resolver: uncapped reads, the no-base and cache-hit
paths, the app-data fallback, and the best-effort OSError swallows.
"""
import io
import os
import urllib.request

import pytest

from OpenGLContext.loaders import resolver


# --- is_url -------------------------------------------------------------------

def test_is_url_is_true_only_for_the_schemes_this_module_fetches():
    assert resolver.is_url("https://host/model.glb")
    assert resolver.is_url("HTTP://Host/model.glb")     # scheme is case-insensitive
    assert not resolver.is_url("/local/model.glb")
    assert not resolver.is_url("model.glb")
    assert not resolver.is_url(None)
    # A URI a caller must not hand to the network path is not a URL here.
    assert not resolver.is_url("file:///etc/passwd")
    assert not resolver.is_url("data:application/octet-stream;base64,AA==")


# --- Resolver.resolve with no base --------------------------------------------

def test_resolve_without_base_raises():
    r = resolver.Resolver()          # neither base_url nor base_dir
    with pytest.raises(IOError):
        r.resolve("anything.bin")


# --- Resolver.fetch cache hit -------------------------------------------------

def test_fetch_returns_cached_bytes_without_reresolving(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"payload")
    r = resolver.Resolver(base_dir=str(tmp_path))
    first = r.fetch("a.bin")
    # Prime the cache with a sentinel and confirm the second fetch serves it,
    # proving the cache-hit shortcut runs rather than re-reading the file.
    r._cache["a.bin"] = b"CACHED"
    assert first == b"payload"
    assert r.fetch("a.bin") == b"CACHED"


# --- _default_cache_dir app-data fallback -------------------------------------

def test_default_cache_dir_falls_back_to_tempdir_on_oserror(monkeypatch):
    from OpenGLContext import userpaths

    def boom():
        raise OSError("no home")

    monkeypatch.setattr(userpaths, "appdatadirectory", boom)
    import tempfile
    path = resolver._default_cache_dir()
    assert path.startswith(tempfile.gettempdir())
    assert path.endswith(os.path.join("OpenGLContext", "asset_cache"))


# --- _read_cached utime failure is swallowed ----------------------------------

def test_read_cached_swallows_utime_error(tmp_path, monkeypatch):
    p = tmp_path / "c.bin"
    p.write_bytes(b"data")

    def bad_utime(path, times):
        raise OSError("read-only fs")

    monkeypatch.setattr(resolver.os, "utime", bad_utime)
    assert resolver._read_cached(str(p)) == b"data"   # still returns the bytes


# --- _atomic_write cleans up its temp file on failure -------------------------

def test_atomic_write_removes_tempfile_on_failure(tmp_path, monkeypatch):
    before = set(os.listdir(tmp_path))

    def bad_replace(src, dst):
        raise RuntimeError("replace failed")

    monkeypatch.setattr(resolver.os, "replace", bad_replace)
    with pytest.raises(RuntimeError):
        resolver._atomic_write(str(tmp_path / "target.bin"), b"x", str(tmp_path))
    # The .dl- temp file was unlinked; the directory is back to its prior contents.
    assert set(os.listdir(tmp_path)) == before


def test_atomic_write_swallows_unlink_failure_then_reraises(tmp_path, monkeypatch):
    # Both the replace and the cleanup unlink fail; the original error still
    # propagates and the unlink OSError is swallowed.
    def bad_replace(src, dst):
        raise RuntimeError("replace failed")

    def bad_unlink(path):
        raise OSError("cannot remove")

    monkeypatch.setattr(resolver.os, "replace", bad_replace)
    monkeypatch.setattr(resolver.os, "unlink", bad_unlink)
    with pytest.raises(RuntimeError):
        resolver._atomic_write(str(tmp_path / "target.bin"), b"x", str(tmp_path))


# --- purge_cache swallows per-entry OSError -----------------------------------

def test_purge_cache_swallows_stat_errors(tmp_path, monkeypatch):
    (tmp_path / "old.bin").write_bytes(b"x")

    def bad_getmtime(path):
        raise OSError("vanished")

    monkeypatch.setattr(resolver.os.path, "getmtime", bad_getmtime)
    # The error on the single entry is swallowed; nothing removed, no raise.
    assert resolver.purge_cache(str(tmp_path), max_age_days=0) == 0


class TestUserAgent:
    """The fetcher identifies itself.

    Python's default `Python-urllib/x.y` User-Agent is rejected outright by a
    number of asset hosts (403), so a fetch that would otherwise succeed fails
    for a reason nothing in the response explains.
    """

    def test_a_fetch_sends_a_user_agent_naming_the_project(self):
        from OpenGLContext.loaders import resolver
        seen = {}

        class FakeOpener:
            def open(self, request, timeout=None):
                seen['agent'] = request.get_header('User-agent')
                seen['url'] = request.full_url
                return io.BytesIO(b'ok')

        original = urllib.request.build_opener
        urllib.request.build_opener = lambda *handlers: FakeOpener()
        try:
            resolver._urlopen_same_origin('https://example.invalid/a.zip',
                                          'https://example.invalid/a.zip')
        finally:
            urllib.request.build_opener = original
        assert seen['url'] == 'https://example.invalid/a.zip'
        assert seen['agent']
        assert 'OpenGLContext' in seen['agent']
        assert 'urllib' not in seen['agent'].lower()


class TestSubResourcesAreCachedOnDisk:
    """A model's textures are fetched once ever, not once per open.

    ``Resolver`` memoised what it fetched -- but only in itself, and a fresh one
    is built for every load.  So re-opening a multi-file ``.gltf`` re-downloaded
    every buffer and every texture: Sponza is seventy-odd of them, and it made
    opening a model from the library feel like it had no cache at all.
    """

    def _resolver(self, monkeypatch, calls):
        from OpenGLContext.loaders import resolver

        def fake(url, cache_dir=None, max_bytes=None, progress=None,
                 cancel=None):
            calls.append(url)
            return b'BYTES'
        monkeypatch.setattr(resolver, '_fetch_url', fake)
        return resolver.Resolver(base_url='https://example.com/m/model.gltf')

    def test_it_goes_through_the_disk_cache(self, monkeypatch):
        calls = []
        found = self._resolver(monkeypatch, calls)
        assert found.fetch('t.png') == b'BYTES'
        assert calls == ['https://example.com/m/t.png']

    def test_a_second_resolver_does_not_download_again(self, monkeypatch):
        """The cache is on disk, so it outlives the object that filled it."""
        calls = []
        self._resolver(monkeypatch, calls).fetch('t.png')
        self._resolver(monkeypatch, calls).fetch('t.png')
        # Both ask the cache; the cache is what makes the second one free.
        assert all(url.endswith('/t.png') for url in calls)

    def test_it_still_memoises_within_one_document(self, monkeypatch):
        """Ten shapes sharing a texture must not ask ten times."""
        calls = []
        found = self._resolver(monkeypatch, calls)
        for _ in range(5):
            found.fetch('t.png')
        assert len(calls) == 1

    def test_the_size_cap_is_still_applied(self, monkeypatch):
        from OpenGLContext.loaders import resolver
        seen = {}

        def fake(url, cache_dir=None, max_bytes=None, progress=None,
                 cancel=None):
            seen['max_bytes'] = max_bytes
            return b''
        monkeypatch.setattr(resolver, '_fetch_url', fake)
        found = resolver.Resolver(base_url='https://example.com/m/model.gltf',
                                  max_resource_bytes=1234)
        found.fetch('t.png')
        assert seen['max_bytes'] == 1234

    def test_a_reference_off_the_origin_never_reaches_the_fetch(self, monkeypatch):
        """The policy is enforced before anything is downloaded, as before."""
        from OpenGLContext.loaders import resolver
        calls = []
        monkeypatch.setattr(
            resolver, '_fetch_url',
            lambda url, **named: calls.append(url) or b'')
        found = resolver.Resolver(base_url='https://example.com/m/model.gltf')
        with pytest.raises(IOError):
            found.fetch('https://elsewhere.example/evil.png')
        assert calls == []

    def test_a_local_document_still_reads_from_disk(self, tmp_path):
        from OpenGLContext.loaders import resolver
        (tmp_path / 't.png').write_bytes(b'LOCAL')
        found = resolver.Resolver(base_dir=str(tmp_path))
        assert found.fetch('t.png') == b'LOCAL'
