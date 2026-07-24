"""Extra coverage for loaders.resolver: uncapped reads, the no-base and cache-hit
paths, the app-data fallback, and the best-effort OSError swallows.
"""
import os

import pytest

from OpenGLContext.loaders import resolver


# --- _read_capped uncapped path -----------------------------------------------

def test_read_capped_without_limit_reads_all():
    class _Resp:
        def read(self, *a):
            return b"unbounded-body"

    assert resolver._read_capped(_Resp(), None) == b"unbounded-body"


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
    from OpenGLContext.browser import homedirectory

    def boom():
        raise OSError("no home")

    monkeypatch.setattr(homedirectory, "appdatadirectory", boom)
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
