"""A URL field's background load never keeps the interpreter alive.

Setting the ``url`` of an ImageTexture, an Inline or a GLSL shader hands the
fetch to the loader pool (:mod:`OpenGLContext.loaders.background`). Python joins
every non-daemon thread as it shuts down, so a fetch that never answers -- or
one waiting on the context lock for a frame that will not come -- would hold the
process open after everything else finished.
"""
import threading

import pytest

from OpenGLContext.loaders import background
from OpenGLContext.scenegraph import imagetexture, inline, shaders

#: How long a test waits for a load that should take milliseconds.
PATIENCE = 20.0


def loader_threads():
    return [thread for thread in threading.enumerate()
            if thread.name.startswith('oglc-load')]


@pytest.mark.parametrize('node', [
    imagetexture.ImageTexture,
    inline.Inline,
    shaders.GLSLShader,
    shaders.GLSLImport,
], ids=lambda node: node.__name__)
def test_setting_a_url_loads_on_a_daemon(node):
    node(url=['nowhere.invalid'])
    assert background.wait_for_idle(PATIENCE), 'the load never finished'
    started = loader_threads()
    assert started, 'no background load was started'
    assert all(thread.daemon for thread in started), [
        thread.name for thread in started if not thread.daemon]


def test_every_fragment_of_a_shader_is_fetched(caplog):
    """A shader's source may be spread over several urls, and all of them are
    read before the fragments are joined into one."""
    shader = shaders.GLSLShader()
    field = type(shader).url
    field.loadBackground(shader, ['one.invalid', 'two.invalid'], [])
    assert 'one.invalid' in caplog.text
    assert 'two.invalid' in caplog.text
