"""The pointer's shape, asked of every window system that can answer.

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

from OpenGLContext.context import Context, CURSORS
from OpenGLContext.testing import glcontext
from OpenGLContext.windowsystem import glut as glutsystem
from OpenGLContext.windowsystem.base import WindowSystem
from OpenGLContext.windowsystem.glfw import GLFWWindowSystem
from OpenGLContext.windowsystem.glut import GLUTWindowSystem

#: Every name the GLFW window system offers.
NAMES = sorted(GLFWWindowSystem.CURSOR_SHAPES)


@pytest.fixture
def window(gl_window):
    """A hidden GLFW window, current for the test; its handle."""
    if glcontext.windowing() != 'glfw':
        pytest.skip('this run makes its contexts without GLFW windows')
    return gl_window('cursor')


def _Window(handle):
    """A context whose GLFW window system is drawing into ``handle``

    The window was made by the fixture, which owns it; the window system's
    cursor code runs over it as it would over one it had opened itself.
    """
    context = Context.__new__(Context)
    context.windowsystem = GLFWWindowSystem(context)
    context.windowsystem.window = handle
    return context


class _NoCursors(WindowSystem):
    """A window system that provides only what every one must, and no cursors"""

    def open(self, definition, parent=None):
        return True

    def release(self):
        pass

    def makeCurrent(self):
        return None

    def swap(self):
        pass

    def drawableSize(self):
        return (1, 1)


def _cursorless():
    """A context over a window system with no pointer shapes"""
    context = Context.__new__(Context)
    context.windowsystem = _NoCursors(context)
    return context


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
    monkeypatch.setitem(GLFWWindowSystem.CURSOR_SHAPES, 'nothing',
                        ('NO_SUCH_CURSOR',))
    assert not _Window(window).setPointerShape('nothing')


def test_the_same_shape_is_made_once(window):
    context = _Window(window)
    assert context.setPointerShape('arrow')
    made = dict(context.windowsystem._cursors)  # noqa: SLF001 the window system's cursor table is what this test counts
    assert context.setPointerShape('arrow')
    assert context.windowsystem._cursors == made  # noqa: SLF001 the window system's cursor table is what this test counts


def test_the_shapes_go_with_the_window(window, monkeypatch):
    """A process that opens many windows does not collect their cursors."""
    context = _Window(window)
    assert context.setPointerShape('arrow')
    made = list(context.windowsystem._cursors.values())  # noqa: SLF001 the window system's cursor table is what this test counts
    destroyed = []
    real = glfw.destroy_cursor

    def destroying(cursor):
        destroyed.append(cursor)
        real(cursor)

    monkeypatch.setattr(glfw, 'destroy_cursor', destroying)
    # The fixture owns the window and its GL objects; only the cursors are
    # this context's to let go of here.
    monkeypatch.setattr(glfw, 'destroy_window', lambda _handle: None)
    monkeypatch.setattr(context, 'releaseContextResources',
                        lambda _handle: None, raising=False)
    context.releaseWindow()
    assert destroyed == made
    assert not context.windowsystem._cursors  # noqa: SLF001 the window system's cursor table is what this test counts
    glfw.make_context_current(window)


def test_a_context_with_no_window_sets_nothing():
    assert not _Window(None).setPointerShape('hand')


def test_a_context_that_cannot_change_it_says_so():
    """The base class answers for every window system that has no cursors."""
    assert not _cursorless().setPointerShape('hand')



class TestEveryWindowSystemSpeaksTheSameWords:
    """A control asks for a shape by name; the window systems map it to their own.

    The names are ``OpenGLContext.context.CURSORS``. What is held here is that
    each window system's table is written in those words and in no others, so
    a control that asks for ``resize-x`` gets the resize pointer wherever it
    runs and a typo in a table is a failure rather than a pointer that never
    changes.
    """

    def _windowSystems(self):
        """Each window-system class that offers shapes, by module name."""
        found = {}
        for module, name in (('glfw', 'GLFWWindowSystem'),
                             ('glut', 'GLUTWindowSystem'),
                             ('pygame', 'PygameWindowSystem'),
                             ('tk', 'TkWindowSystem'),
                             ('wx', 'WxWindowSystem')):
            try:
                imported = __import__('OpenGLContext.windowsystem.%s' % module,
                                      fromlist=[name])
            except ImportError:
                continue
            system = getattr(imported, name, None)
            shapes = getattr(system, 'CURSOR_SHAPES', None)
            if shapes is not None:
                found[module] = shapes
        assert found, 'no window system offered any pointer shapes'
        return found

    def test_each_table_is_written_in_the_engines_names(self):
        for module, shapes in self._windowSystems().items():
            for name in shapes:
                assert name in CURSORS, (module, name)

    def test_each_window_system_has_the_ordinary_pointer(self):
        for module, shapes in self._windowSystems().items():
            assert 'arrow' in shapes, module

    def test_a_window_system_that_offers_none_answers_no(self):
        assert not _cursorless().setPointerShape('hand')

    def test_the_window_system_this_run_uses_offers_them(self):
        assert 'glfw' in self._windowSystems()


class TestMouseLookKeepsThePointerHidden:
    """A window system whose hidden pointer is itself a cursor shape refuses another."""

    def test_glut_refuses_a_shape_while_the_pointer_is_grabbed(self, monkeypatch):
        set_to = []
        monkeypatch.setattr(glutsystem, 'glutSetWindow', lambda _window: None)
        monkeypatch.setattr(glutsystem, 'glutSetCursor', set_to.append)
        context = Context.__new__(Context)
        context.windowsystem = GLUTWindowSystem(context)
        context.windowsystem.window = 1
        context.windowsystem.pointerGrabbed = True
        assert not context.setPointerShape('hand')
        assert set_to == []
        context.windowsystem.pointerGrabbed = False
        assert context.setPointerShape('hand')
        assert set_to == [GLUT.GLUT_CURSOR_INFO]


class TestNoWrongPicture:
    """A window system with no "not allowed" pointer answers False rather than show another."""

    def test_glut_has_no_not_allowed_pointer(self, monkeypatch):
        set_to = []
        monkeypatch.setattr(glutsystem, 'glutSetWindow', lambda _window: None)
        monkeypatch.setattr(glutsystem, 'glutSetCursor', set_to.append)
        context = Context.__new__(Context)
        context.windowsystem = GLUTWindowSystem(context)
        context.windowsystem.window = 1
        assert not context.setPointerShape('no')
        assert set_to == []

    def test_tk_has_no_not_allowed_pointer(self):
        from OpenGLContext.windowsystem.tk import TkWindowSystem  # noqa: PLC0415 tkinter is optional in a Python build
        assert 'no' not in TkWindowSystem.CURSOR_SHAPES
