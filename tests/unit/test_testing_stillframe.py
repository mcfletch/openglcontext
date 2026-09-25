"""``check_still_frame`` counts the GL work of a frame and holds it to a floor."""
import numpy as np
import pytest
from OpenGL import GL
from OpenGL.GL import glGenBuffers as made_under_another_name

from OpenGLContext.testing.stillframe import (
    StillFrameWork,
    check_still_frame,
    counting_gl,
    still_frame_work,
)


def _fill(buffers):
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buffers[0])
    GL.glBufferData(GL.GL_ARRAY_BUFFER, 16, np.zeros(4, 'f'), GL.GL_STATIC_DRAW)


def test_calls_are_counted_by_name_and_by_where_they_were_made(gl_context):
    original = GL.glGenBuffers
    with counting_gl() as work:
        buffer = made_under_another_name(1)
        _fill([buffer])
    assert work.calls == {'glGenBuffers': 1, 'glBufferData': 1}
    assert (work.allocations, work.uploads, work.compiles) == (1, 1, 0)
    assert any(site.startswith(__name__ + ':') for _name, site in work.sites)
    assert GL.glGenBuffers is original and made_under_another_name is original
    GL.glDeleteBuffers(1, [buffer])


def test_a_frame_that_fills_a_buffer_fails_a_floor_of_nothing(gl_context):
    buffers = [GL.glGenBuffers(1)]
    with pytest.raises(StillFrameWork, match='uploads: 1, the floor is 0'):
        check_still_frame(lambda: _fill(buffers), warmup=1)
    assert check_still_frame(lambda: _fill(buffers), uploads=1).uploads == 1
    GL.glDeleteBuffers(1, buffers)


def test_a_frame_that_does_nothing_passes():
    work = still_frame_work(lambda: None, warmup=0)
    assert str(work) == '0 allocations, 0 uploads, 0 compiles (no counted calls)'


def test_the_plugin_offers_it_as_a_fixture(check_still_frame):
    assert check_still_frame(lambda: None).allocations == 0
