"""A URL field's background load never keeps the interpreter alive.

Setting the ``url`` of an ImageTexture, an Inline or a GLSL shader starts a
thread to fetch it. Python joins every non-daemon thread as it shuts down, so a
fetch that never answers -- or one waiting on the context lock for a frame that
will not come -- would hold the process open after everything else finished.
"""
import threading

import pytest

from OpenGLContext.scenegraph import imagetexture, inline, shaders


class RecordedThread:
    """Stands in for ``threading.Thread``: remembers what was asked, runs nothing."""

    started: list = []

    def __init__(self, *args, name=None, daemon=None, **named):
        self.name = name
        self.daemon = daemon

    def start(self):
        RecordedThread.started.append(self)

    def join(self, timeout=None):
        pass


@pytest.fixture
def started(monkeypatch):
    RecordedThread.started = []
    monkeypatch.setattr(threading, 'Thread', RecordedThread)
    return RecordedThread.started


@pytest.mark.parametrize('node', [
    imagetexture.ImageTexture,
    inline.Inline,
    shaders.GLSLShader,
    shaders.GLSLImport,
], ids=lambda node: node.__name__)
def test_setting_a_url_starts_a_daemon(node, started):
    node(url=['nowhere.invalid'])
    assert started, 'no background load was started'
    assert all(thread.daemon for thread in started), [
        thread.name for thread in started if not thread.daemon]


def test_each_shader_fragment_loads_in_a_daemon(started):
    """A shader's URLs are fetched one thread apiece, and each is a daemon too."""
    shader = shaders.GLSLShader()
    field = type(shader).url
    field.loadBackground(shader, ['one.invalid', 'two.invalid'], [])
    assert len(started) == 2
    assert all(thread.daemon for thread in started)
