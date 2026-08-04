"""Bounds and identity for the ambientCG material fetcher.

`loaders/cc0.py` downloads a CC0 material archive and extracts four maps from it.
It runs from `oglc-terrain` and from `SplatTerrain`, so it reaches the network on
an ordinary first use, and both the download and the archive it expands have to
be bounded: an archive is compressed, so its members can be far larger than the
bytes that arrived.
"""
import io
import zipfile

import pytest

from OpenGLContext.loaders import cc0


def _archive(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in members.items():
            z.writestr(name, payload)
    return buf.getvalue()


class TestTheUserAgent:
    def test_it_names_the_project_rather_than_a_browser(self):
        agent = cc0._UA["User-Agent"]
        assert "OpenGLContext" in agent
        assert "Mozilla" not in agent


class TestTheDownloadIsBounded:
    def test_an_over_size_archive_is_refused(self, monkeypatch):
        monkeypatch.setattr(cc0, "_api_download_link",
                            lambda asset, resolution: "https://x.invalid/a.zip")
        monkeypatch.setattr(cc0, "_read_capped", _refuse)
        with pytest.raises(ValueError):
            cc0._download("Bark012")


def _refuse(url, max_bytes):
    raise ValueError("resource is over the %d-byte limit" % (max_bytes,))


class TestTheArchiveIsBounded:
    """A zip bomb must not be written to disk map by map."""

    def test_an_over_size_member_is_refused(self, tmp_path, monkeypatch):
        blob = _archive({"Bark012_1K_Color.jpg": b"\0" * (4 * 1024 * 1024)})
        monkeypatch.setattr(cc0, "cache_dir", lambda: str(tmp_path))
        monkeypatch.setattr(cc0, "_download",
                            lambda asset, resolution: zipfile.ZipFile(io.BytesIO(blob)))
        with pytest.raises(ValueError):
            cc0.material("bark", max_member_bytes=1024)

    def test_a_member_within_the_cap_is_written(self, tmp_path, monkeypatch):
        blob = _archive({"Bark012_1K_Color.jpg": b"jpeg-ish",
                         "Bark012_1K_NormalGL.jpg": b"jpeg-ish"})
        monkeypatch.setattr(cc0, "cache_dir", lambda: str(tmp_path))
        monkeypatch.setattr(cc0, "_download",
                            lambda asset, resolution: zipfile.ZipFile(io.BytesIO(blob)))
        got = cc0.material("bark")
        assert set(got) == {"color", "normal"}
        assert open(got["color"], "rb").read() == b"jpeg-ish"

    def test_try_material_still_swallows_the_refusal(self, tmp_path, monkeypatch):
        blob = _archive({"Bark012_1K_Color.jpg": b"\0" * (4 * 1024 * 1024)})
        monkeypatch.setattr(cc0, "cache_dir", lambda: str(tmp_path))
        monkeypatch.setattr(cc0, "_download",
                            lambda asset, resolution: zipfile.ZipFile(io.BytesIO(blob)))
        assert cc0.try_material("bark", max_member_bytes=1024) is None


class TestTheCacheLocation:
    def test_it_is_under_the_per_user_app_data_directory(self, tmp_path, monkeypatch):
        from OpenGLContext import userpaths
        monkeypatch.setattr(userpaths, "appdatadirectory", lambda: str(tmp_path))
        assert cc0.cache_dir() == str(tmp_path / "OpenGLContext" / "cc0")

    def test_the_cache_is_not_readable_by_other_accounts(self, tmp_path, monkeypatch):
        import os
        from OpenGLContext import userpaths
        monkeypatch.setattr(userpaths, "appdatadirectory", lambda: str(tmp_path))
        created = cc0.cache_dir()
        assert (os.stat(created).st_mode & 0o077) == 0
