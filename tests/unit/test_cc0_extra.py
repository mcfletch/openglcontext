"""Coverage for loaders.cc0 (ambientCG CC0 fetch) with the network mocked.

The real module downloads a material zip over https; here urllib is replaced with a
fake that serves a canned API JSON and an in-memory zip, so the download/extract/
cache/manifest paths run fully offline.
"""
import io
import json
import zipfile

import pytest

from OpenGLContext.loaders import cc0


@pytest.fixture(autouse=True)
def cache_under_tmp(tmp_path, monkeypatch):
    """Keep every test's downloads out of the real per-user cache."""
    from OpenGLContext import userpaths
    monkeypatch.setattr(userpaths, "appdatadirectory", lambda: str(tmp_path))


def _fake_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Bark012_1K_Color.jpg", b"colorbytes")
        z.writestr("Bark012_1K_NormalGL.jpg", b"normalbytes")
        z.writestr("Bark012_1K_Roughness.jpg", b"roughbytes")
        z.writestr("Bark012_1K_AmbientOcclusion.jpg", b"aobytes")
    return buf.getvalue()


def _api_json(with_jpg=True):
    attribute = "1K-JPG" if with_jpg else "2K-PNG"
    return {
        "foundAssets": [{
            "downloadFolders": {"default": {"downloadFiletypeCategories": {
                "zip": {"downloads": [
                    {"attribute": attribute,
                     "downloadLink": "https://ambientcg.com/get/Bark012_1K.zip"},
                ]},
            }}},
        }],
    }


class _Resp:
    """A stand-in for an http response, read in chunks as the real one is."""

    def __init__(self, data):
        self._rest = data
        self.headers = {"Content-Length": str(len(data))}

    def read(self, size=None):
        if size is None:
            chunk, self._rest = self._rest, b""
            return chunk
        chunk, self._rest = self._rest[:size], self._rest[size:]
        return chunk

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _install_fake_net(monkeypatch, api_json, zip_bytes=None):
    def fake_urlopen(request, timeout=None, context=None):
        url = request.full_url
        if "api/v2" in url:
            return _Resp(json.dumps(api_json).encode("utf-8"))
        return _Resp(zip_bytes if zip_bytes is not None else _fake_zip())

    monkeypatch.setattr(cc0.urllib.request, "urlopen", fake_urlopen)


def test_material_downloads_extracts_and_caches(tmp_path, monkeypatch):
    _install_fake_net(monkeypatch, _api_json())

    maps = cc0.material("bark")            # "bark" -> asset Bark012
    for kind in ("color", "normal", "roughness", "ao"):
        assert kind in maps
        with open(maps[kind], "rb") as fh:
            assert fh.read()               # each map extracted to disk
    # A CREDITS manifest recording provenance was written.
    import os
    credits = os.path.join(cc0.cache_dir(), "CREDITS.txt")
    assert "Bark012" in open(credits).read()


def test_material_reuses_cache_without_redownloading(tmp_path, monkeypatch):
    _install_fake_net(monkeypatch, _api_json())
    cc0.material("bark")                    # first call populates the cache

    def explode(*a, **k):
        raise AssertionError("must not hit the network on a cache hit")

    monkeypatch.setattr(cc0.urllib.request, "urlopen", explode)
    maps = cc0.material("bark")             # color+normal exist -> cached path
    assert "color" in maps and "normal" in maps


def test_manifest_not_duplicated_on_second_material(tmp_path, monkeypatch):
    _install_fake_net(monkeypatch, _api_json())
    cc0._write_manifest("Rock030", "1K")
    cc0._write_manifest("Rock030", "1K")   # identical line -> not appended twice
    import os
    text = open(os.path.join(cc0.cache_dir(), "CREDITS.txt")).read()
    assert text.count("Rock030 (1K)") == 1


def test_write_manifest_swallows_os_error(tmp_path, monkeypatch):
    import os
    # A directory where the CREDITS file should be makes open() raise OSError,
    # which _write_manifest must swallow rather than propagate.
    os.mkdir(os.path.join(cc0.cache_dir(), "CREDITS.txt"))
    cc0._write_manifest("Rock030", "1K")   # must not raise


def test_download_without_matching_jpg_raises(tmp_path, monkeypatch):
    _install_fake_net(monkeypatch, _api_json(with_jpg=False))
    with pytest.raises(RuntimeError):
        cc0._download("Bark012")


def test_try_material_returns_none_on_failure(tmp_path, monkeypatch):

    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(cc0.urllib.request, "urlopen", boom)
    assert cc0.try_material("bark") is None


def test_cache_dir_is_under_the_per_user_app_data_directory(tmp_path, monkeypatch):
    # Shared with the rest of OpenGLContext's downloaded assets, so no other
    # account can pre-seed a texture this user then loads.
    import os
    from OpenGLContext import userpaths
    monkeypatch.setattr(userpaths, "appdatadirectory", lambda: str(tmp_path))
    assert cc0.cache_dir() == os.path.join(str(tmp_path), "OpenGLContext", "cc0")
