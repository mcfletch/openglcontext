"""Bounds and identity for the ambientCG material fetcher.

`loaders/cc0.py` downloads a CC0 material archive and extracts four maps from it.
It runs from `oglc-terrain` and from `SplatTerrain`, so it reaches the network on
an ordinary first use, and both the download and the archive it expands have to
be bounded: an archive is compressed, so its members can be far larger than the
bytes that arrived.
"""
import io
import os
import zipfile

import pytest

from OpenGLContext.loaders import cc0
from OpenGLContext import userpaths


def _archive(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in members.items():
            z.writestr(name, payload)
    return buf.getvalue()


class TestTheUserAgent:
    def test_it_names_the_project_rather_than_a_browser(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc0, "cache_dir", lambda: str(tmp_path))
        sent = []

        def opened(url, redirects=None, timeout=30, agent=None):
            sent.append(agent or cc0.resolver.user_agent())
            raise OSError("offline")

        monkeypatch.setattr(cc0.resolver, "open_url", opened)
        assert cc0.try_material("bark") is None
        assert "OpenGLContext" in sent[0]
        assert "Mozilla" not in sent[0]


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
        monkeypatch.setattr(userpaths, "appdatadirectory", lambda: str(tmp_path))
        assert cc0.cache_dir() == str(tmp_path / "OpenGLContext" / "cc0")

    def test_the_cache_is_not_readable_by_other_accounts(self, tmp_path, monkeypatch,
                                                         posix_modes):
        if not posix_modes:
            pytest.skip('this filesystem does not enforce POSIX directory modes')
        monkeypatch.setattr(userpaths, "appdatadirectory", lambda: str(tmp_path))
        created = cc0.cache_dir()
        assert (os.stat(created).st_mode & 0o077) == 0


class TestWhereTheArchiveMayComeFrom:
    """The API answers with a download link, and that answer is data.

    ambientCG says where the archive is and the loader fetches it. A service
    that is compromised or wrong can name anywhere at all, so the link is
    checked against the hosts ambientCG publishes from before it is followed --
    the same rule a document's own references go through.
    """

    def _answering(self, monkeypatch, link):
        """Make the API answer with ``link`` and record what gets fetched."""
        fetched = []

        def _api(asset, resolution):
            return cc0._require_download_host(link)

        monkeypatch.setattr(cc0, "_api_download_link", _api)
        monkeypatch.setattr(cc0, "_read_capped",
                            lambda url, cap: fetched.append(url) or b"")
        return fetched

    def test_an_ambientcg_link_is_followed(self, monkeypatch):
        fetched = self._answering(
            monkeypatch, "https://ambientcg.com/get?file=Bark012_1K-JPG.zip")

        with pytest.raises(zipfile.BadZipFile):
            cc0._download("Bark012")

        assert fetched == ["https://ambientcg.com/get?file=Bark012_1K-JPG.zip"]

    def test_a_link_to_somewhere_else_is_refused(self, monkeypatch):
        fetched = self._answering(monkeypatch, "https://evil.example/a.zip")

        with pytest.raises(IOError):
            cc0._download("Bark012")

        assert fetched == []

    def test_a_file_url_is_refused(self, monkeypatch):
        self._answering(monkeypatch, "file:///etc/passwd")

        with pytest.raises(IOError):
            cc0._download("Bark012")

    def test_a_plaintext_link_is_refused(self, monkeypatch):
        self._answering(monkeypatch, "http://ambientcg.com/get?file=x.zip")

        with pytest.raises(IOError):
            cc0._download("Bark012")


class TestTheApiAnswerIsBounded:
    def test_an_unbounded_answer_is_refused(self, monkeypatch):
        """A JSON body is read into memory before it is parsed, so its size is
        as much a limit as the archive's is."""
        monkeypatch.setattr(cc0, "_read_capped", _refuse)

        with pytest.raises(ValueError):
            cc0._api_download_link("Bark012", "1K")
