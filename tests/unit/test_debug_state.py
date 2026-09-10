"""`OpenGLContext.debug.state` captures fixed-function GL state and diffs it."""
import pytest

from OpenGL.GL import GL_LIGHTING, glClearColor, glDisable, glEnable

from OpenGLContext.debug import state


@pytest.fixture
def gl_context(gl_window):
    return gl_window('debug-state', size=(16, 16), profile='compatibility')


def test_state_captures_the_named_arguments(gl_context):
    captured = state.State()
    assert 'GL_LIGHTING' in captured
    assert 'GL_VENDOR' in captured


def test_diff_of_an_unchanged_context_is_empty(gl_context):
    """The multi-valued state -- the clear colour, the viewport -- compares."""
    before = state.State()
    assert state.State().diff(before) == {}


def test_diff_reports_a_changed_flag(gl_context):
    glDisable(GL_LIGHTING)
    before = state.State()
    glEnable(GL_LIGHTING)
    diffs = state.State().diff(before)
    assert diffs['GL_LIGHTING'] == (0, 1)


def test_diff_reports_a_changed_multi_valued_setting(gl_context):
    glClearColor(0.0, 0.0, 0.0, 1.0)
    before = state.State()
    glClearColor(1.0, 0.0, 0.0, 1.0)
    diffs = state.State().diff(before)
    old, new = diffs['GL_COLOR_CLEAR_VALUE']
    assert list(old) != list(new)
