"""Where a VRML ``AudioSource`` is allowed to look for its sound.

An ``AudioSource`` in a scene file names its clip by ``url``, relative to the
document. For a document from an untrusted source that string is chosen by
whoever wrote it, so it is held to the same rule as every other external
reference (:mod:`OpenGLContext.loaders.resolver`): a scene loaded from disk may
only read audio under its own directory, and one fetched over http(s) may only
pull same-origin audio.

A source built in application code has no document behind it, so nothing is
confined -- that name came from the application, not from a file.
"""
from typing import Any, List, Optional

import pytest

from OpenGLContext.scenegraph import audio


class _Engine:
    """Records the names it is asked for and hands back a stand-in clip."""

    def __init__(self, known: Optional[dict] = None) -> None:
        self.asked: List[str] = []
        self._known = known or {}

    def clip(self, name: str) -> Any:
        self.asked.append(name)
        return self._known.get(name)


class _Root:
    """Stands in for the scenegraph root a loaded document hangs off."""

    def __init__(self, baseURI: Optional[str]) -> None:
        self.baseURI = baseURI


@pytest.fixture
def rooted(monkeypatch):
    """Give an AudioSource a document base, as a loaded scene would."""
    def apply(base: Optional[str]):
        monkeypatch.setattr(audio.protofunctions, "root",
                            lambda node: _Root(base) if base is not None else None)
    return apply


class TestASourceInADocumentOnDisk:
    def test_a_sibling_file_is_resolved_to_its_absolute_path(self, tmp_path, rooted):
        (tmp_path / "shot.wav").write_bytes(b"")
        rooted(str(tmp_path / "scene.wrl"))
        engine = _Engine()
        audio.AudioSource(url=["shot.wav"]).clip(engine)
        assert engine.asked == [str(tmp_path / "shot.wav")]

    def test_a_traversal_never_reaches_the_decoder(self, tmp_path, rooted):
        rooted(str(tmp_path / "scene.wrl"))
        engine = _Engine()
        assert audio.AudioSource(url=["../../../etc/shadow"]).clip(engine) is None
        assert engine.asked == []

    def test_an_absolute_path_never_reaches_the_decoder(self, tmp_path, rooted):
        rooted(str(tmp_path / "scene.wrl"))
        engine = _Engine()
        assert audio.AudioSource(url=["/etc/shadow"]).clip(engine) is None
        assert engine.asked == []

    def test_a_url_never_reaches_the_decoder(self, tmp_path, rooted):
        rooted(str(tmp_path / "scene.wrl"))
        engine = _Engine()
        assert audio.AudioSource(url=["http://169.254.169.254/"]).clip(engine) is None
        assert engine.asked == []

    def test_a_refused_entry_does_not_stop_a_later_good_one(self, tmp_path, rooted):
        (tmp_path / "shot.wav").write_bytes(b"")
        rooted(str(tmp_path / "scene.wrl"))
        good = str(tmp_path / "shot.wav")
        engine = _Engine({good: "clip"})
        source = audio.AudioSource(url=["/etc/shadow", "shot.wav"])
        assert source.clip(engine) == "clip"
        assert engine.asked == [good]


class TestASourceInADocumentOverHttp:
    def test_a_same_origin_clip_is_resolved(self, rooted):
        rooted("https://host.invalid/scenes/a.wrl")
        engine = _Engine()
        audio.AudioSource(url=["sfx/shot.wav"]).clip(engine)
        assert engine.asked == ["https://host.invalid/scenes/sfx/shot.wav"]

    def test_another_host_never_reaches_the_decoder(self, rooted):
        rooted("https://host.invalid/scenes/a.wrl")
        engine = _Engine()
        assert audio.AudioSource(url=["http://evil.invalid/x.wav"]).clip(engine) is None
        assert engine.asked == []


class TestASourceBuiltInCode:
    def test_nothing_is_confined_without_a_document(self, rooted):
        # The application named this, so it is not a document's reference.
        rooted(None)
        engine = _Engine()
        audio.AudioSource(url=["/opt/sounds/shot.wav"]).clip(engine)
        assert engine.asked == ["/opt/sounds/shot.wav"]
