"""The pointer's shape, asked of every backend that can answer.

A control that drags says so by the cursor over it, which means the window has
to be able to change it. GLFW carries the standard shapes, but a platform's
cursor theme need not: a Wayland session with a minimal theme has the arrow
and the text bar and nothing else. So what is held here is that a shape this
platform has is shown, and one it has not is *answered* -- False, rather than
an exception or a pointer left in a half-set state -- which is what lets a
window fall back to saying it some other way.
"""
import pytest
from OpenGL import GLUT

glfw = pytest.importorskip('glfw')

from OpenGLContext.glfwcontext import GLFWContext
from OpenGLContext.testing import glcontext
from OpenGLContext.context import Context, CURSORS
from OpenGLContext.glutcontext import GLUTContext

#: Every name the backend offers.
NAMES = sorted(GLFWContext.CURSOR_SHAPES)


@pytest.fixture
def window(gl_window):
    """A hidden GLFW window, current for the test; its handle."""
    if glcontext.windowing() != 'glfw':
        pytest.skip('this run makes its contexts without GLFW windows')
    return gl_window('cursor')


class _Window(GLFWContext):
    """The backend's cursor code over a window the fixture made."""

    def __init__(self, handle):
        self.window = handle


@pytest.mark.parametrize('name', NAMES)
def test_every_name_is_answered_one_way_or_the_other(window, name):
    """A theme without a shape is a no, not a raise and not a wrong pointer."""
    assert _Window(window).setPointerShape(name) in (True, False)


def test_the_ordinary_pointer_is_one_every_platform_has(window):
    assert _Window(window).setPointerShape('arrow')
    assert _Window(window).setPointerShape('')


def test_a_name_nobody_has_is_refused(window):
    assert not _Window(window).setPointerShape('teapot')


def test_a_shape_the_theme_has_not_got_is_refused(window, monkeypatch):
    monkeypatch.setitem(_Window.CURSOR_SHAPES, 'nothing', ('NO_SUCH_CURSOR',))
    assert not _Window(window).setPointerShape('nothing')


def test_the_same_shape_is_made_once(window):
    context = _Window(window)
    assert context.setPointerShape('arrow')
    made = dict(context._cursors)
    assert context.setPointerShape('arrow')
    assert context._cursors == made


def test_the_shapes_go_with_the_window(window, monkeypatch):
    """A process that opens many windows does not collect their cursors."""
    context = _Window(window)
    assert context.setPointerShape('arrow')
    made = list(context._cursors.values())
    destroyed = []
    real = glfw.destroy_cursor

    def destroying(cursor):
        destroyed.append(cursor)
        real(cursor)

    monkeypatch.setattr(glfw, 'destroy_cursor', destroying)
    # The fixture owns the window and its GL objects; only the cursors are
    # this context's to let go of here.
    monkeypatch.setattr(glfw, 'destroy_window', lambda handle: None)
    monkeypatch.setattr(_Window, 'releaseContextResources', lambda self, handle: None)
    context.releaseWindow()
    assert destroyed == made
    assert not context._cursors
    glfw.make_context_current(window)


def test_a_context_with_no_window_sets_nothing():
    assert not _Window(None).setPointerShape('hand')


def test_a_context_that_cannot_change_it_says_so():
    """The base class answers for every backend that has no cursors."""
    assert not Context.setPointerShape(object(), 'hand')



class TestEveryBackendSpeaksTheSameWords:
    """A control asks for a shape by name; the backends map it to their own.

    The names are ``OpenGLContext.context.CURSORS``. What is held here is that
    each backend's table is written in those words and in no others, so a
    control that asks for ``resize-x`` gets the resize pointer wherever it runs
    and a typo in a table is a failure rather than a pointer that never
    changes.
    """

    def _backends(self):
        """Each backend class that offers shapes, by module name."""
        found = {}
        for module, name in (('glfwcontext', 'GLFWContext'),
                             ('glutcontext', 'GLUTContext'),
                             ('pygamecontext', 'PygameContext'),
                             ('tkcontext', 'TkContext'),
                             ('wxcontext', 'wxContext')):
            try:
                imported = __import__('OpenGLContext.%s' % module,
                                      fromlist=[name])
            except ImportError:
                continue
            backend = getattr(imported, name, None)
            shapes = getattr(backend, 'CURSOR_SHAPES', None)
            if shapes is not None:
                found[module] = shapes
        assert found, 'no backend offered any pointer shapes'
        return found

    def test_each_table_is_written_in_the_engines_names(self):
        for module, shapes in self._backends().items():
            for name in shapes:
                assert name in CURSORS, (module, name)

    def test_each_backend_has_the_ordinary_pointer(self):
        for module, shapes in self._backends().items():
            assert 'arrow' in shapes, module

    def test_a_backend_that_offers_none_answers_no(self):
        assert not Context.setPointerShape(object(), 'hand')

    def test_the_backend_this_run_uses_offers_them(self):
        assert 'glfwcontext' in self._backends()


class TestMouseLookKeepsThePointerHidden:
    """A backend whose hidden pointer is itself a cursor shape refuses another."""

    def test_glut_refuses_a_shape_while_the_pointer_is_grabbed(self, monkeypatch):
        set_to = []
        monkeypatch.setattr(GLUT, 'glutSetWindow', lambda window: None)
        monkeypatch.setattr(GLUT, 'glutSetCursor', set_to.append)
        context = GLUTContext.__new__(GLUTContext)
        context.windowID = 1
        context._pointerGrabbed = True
        assert not context.setPointerShape('hand')
        assert set_to == []
        context._pointerGrabbed = False
        assert context.setPointerShape('hand')
        assert set_to == [GLUT.GLUT_CURSOR_INFO]


class TestNoWrongPicture:
    """A backend with no "not allowed" pointer answers False rather than show another."""

    def test_glut_has_no_not_allowed_pointer(self, monkeypatch):
        set_to = []
        monkeypatch.setattr(GLUT, 'glutSetWindow', lambda window: None)
        monkeypatch.setattr(GLUT, 'glutSetCursor', set_to.append)
        context = GLUTContext.__new__(GLUTContext)
        context.windowID = 1
        assert not context.setPointerShape('no')
        assert set_to == []

    def test_tk_has_no_not_allowed_pointer(self):
        from OpenGLContext.tkcontext import TkContext  # noqa: PLC0415 tkinter is optional in a Python build
        assert 'no' not in TkContext.CURSOR_SHAPES
