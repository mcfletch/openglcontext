"""Grabbing the pointer for the movement mode that steers with it.

Mouse-look needs unbounded motion: a visible cursor stops at the edge of the
screen and the view stops turning with it.  A mode says whether it wants the
pointer, and the context is what knows how to take it.
"""

import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import modes
from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin


class _Platform:
    submerged = False

    def set_move(self, forward=0.0, strafe=0.0, mode='walk'):
        pass

    def set_fly_move(self, forward=0.0, strafe=0.0, up=0.0):
        pass

    def jump(self):
        pass

    def turn(self, delta):
        pass

    def look(self, delta):
        pass


class _Dispatch:
    def ProcessEvent(self, event):
        return None


class _Context(ViewPlatformMixin, _Dispatch):
    """A context stub that records what it was asked to do with the pointer."""

    drawing = False

    def __init__(self, definition=None):
        self.contextDefinition = definition or ContextDefinition()
        self.platform = _Platform()
        self.captures = []

    def getEventManager(self, kind):
        return None

    def triggerRedraw(self, value=1):
        pass

    def setPointerCapture(self, capture):
        self.captures.append(bool(capture))
        return True


def _context(*mode_nodes):
    return _Context(ContextDefinition(movementModes=list(mode_nodes)))


def test_a_mode_that_steers_with_the_mouse_wants_the_pointer():
    assert modes.FPSMode(name='fps').capturePointer


@pytest.mark.parametrize('mode', [modes.WalkMode(name='walk'),
                                  modes.FlyMode(name='fly'),
                                  modes.SwimMode(name='swim')])
def test_a_mode_steered_by_keys_leaves_the_pointer_alone(mode):
    """Taking the pointer from a mode that has no use for it makes the window
    impossible to leave for no gain."""
    assert not mode.capturePointer


def test_entering_a_mouse_look_mode_captures_the_pointer():
    context = _context(modes.FPSMode(name='fps'))
    context.updateNavigation(0.016)
    assert context.captures == [True]


def test_the_capture_is_not_reapplied_every_frame():
    """A grab is a window-manager call, not something to make sixty times a
    second."""
    context = _context(modes.FPSMode(name='fps'))
    for _ in range(5):
        context.updateNavigation(0.016)
    assert context.captures == [True]


def test_leaving_the_mode_releases_the_pointer():
    context = _context(modes.FPSMode(name='fps'), modes.WalkMode(name='walk'))
    context.updateNavigation(0.016)
    context.getNavigation().select('walk')
    context.updateNavigation(0.016)
    assert context.captures == [True, False]


def test_a_context_with_no_mouse_look_mode_never_touches_the_pointer():
    context = _context(modes.WalkMode(name='walk'))
    context.updateNavigation(0.016)
    assert context.captures == []


def test_the_capture_can_be_suspended_while_something_else_wants_the_pointer():
    """An overlay is clicked with the pointer the mode has taken, so entering
    one has to hand it back."""
    context = _context(modes.FPSMode(name='fps'))
    context.updateNavigation(0.016)
    context.suspendPointerCapture(True)
    assert context.captures == [True, False]
    context.updateNavigation(0.016)
    assert context.captures == [True, False]      # still suspended


def test_resuming_takes_the_pointer_back():
    context = _context(modes.FPSMode(name='fps'))
    context.updateNavigation(0.016)
    context.suspendPointerCapture(True)
    context.suspendPointerCapture(False)
    assert context.captures == [True, False, True]


def test_suspending_when_nothing_is_captured_does_nothing():
    context = _context(modes.WalkMode(name='walk'))
    context.updateNavigation(0.016)
    context.suspendPointerCapture(True)
    context.suspendPointerCapture(False)
    assert context.captures == []


def test_a_context_that_cannot_capture_still_navigates():
    """A backend with no pointer grab must not break the mode that wanted one,
    and must not be asked once a frame for an answer that will not change."""

    class _NoCapture(_Context):
        def setPointerCapture(self, capture):
            super(_NoCapture, self).setPointerCapture(capture)
            return False

    context = _NoCapture(ContextDefinition(
        movementModes=[modes.FPSMode(name='fps')]))
    context.updateNavigation(0.016)
    context.updateNavigation(0.016)
    assert context.captures == [True]
    assert context.contextDefinition.movementMode.name == 'fps'


# -- the GLFW backend ---------------------------------------------------------

def test_the_glfw_backend_disables_the_cursor_to_capture(monkeypatch):
    """GLFW's disabled cursor is the one that reports unbounded motion; hidden
    still stops at the screen edge, which is what mouse-look cannot use."""
    glfw = pytest.importorskip('glfw')
    from OpenGLContext import glfwcontext
    calls = []
    monkeypatch.setattr(glfw, 'set_input_mode',
                        lambda window, mode, value: calls.append((mode, value)))
    monkeypatch.setattr(glfw, 'raw_mouse_motion_supported', lambda: False)
    context = glfwcontext.GLFWContext.__new__(glfwcontext.GLFWContext)
    context.window = object()
    assert context.setPointerCapture(True)
    assert calls == [(glfw.CURSOR, glfw.CURSOR_DISABLED)]
    assert context.setPointerCapture(False)
    assert calls[-1] == (glfw.CURSOR, glfw.CURSOR_NORMAL)


def test_raw_motion_is_asked_for_when_the_platform_has_it(monkeypatch):
    """Unaccelerated motion is what a view wants; pointer acceleration is a
    desktop convenience that makes a turn depend on how fast it started."""
    glfw = pytest.importorskip('glfw')
    from OpenGLContext import glfwcontext
    calls = []
    monkeypatch.setattr(glfw, 'set_input_mode',
                        lambda window, mode, value: calls.append((mode, value)))
    monkeypatch.setattr(glfw, 'raw_mouse_motion_supported', lambda: True)
    context = glfwcontext.GLFWContext.__new__(glfwcontext.GLFWContext)
    context.window = object()
    context.setPointerCapture(True)
    assert (glfw.RAW_MOUSE_MOTION, True) in calls


def test_capturing_without_a_window_is_refused():
    pytest.importorskip('glfw')
    from OpenGLContext import glfwcontext
    context = glfwcontext.GLFWContext.__new__(glfwcontext.GLFWContext)
    context.window = None
    assert not context.setPointerCapture(True)


# -- the mix-in must not shadow the backend ----------------------------------

class _Backend:
    """A backend that really can grab the pointer, as GLFWContext can."""

    def __init__(self):
        self.captures = []

    def setPointerCapture(self, capture):
        self.captures.append(bool(capture))
        return True

    def hasMouseMoveHandlers(self):
        return False


class _MixinFirst(ViewPlatformMixin, _Backend):
    """Ordered as every shipped context is: the mix-in before the backend.

    ``GLFWInteractiveContext`` is ``(ViewPlatformMixin, InteractiveContext,
    GLFWContext)``, so a stub on the mix-in shadows the backend's real
    implementation and mouse-look silently never grabs anything.
    """

    def __init__(self):
        _Backend.__init__(self)


def test_the_backends_pointer_grab_is_reached_through_the_mixin():
    context = _MixinFirst()
    assert context.setPointerCapture(True) is True
    assert context.captures == [True]


def test_a_backend_with_no_grab_still_reports_that_it_cannot():
    class _NoBackend(ViewPlatformMixin):
        pass

    assert _NoBackend().setPointerCapture(True) is False


def test_a_mouse_look_mode_actually_grabs_through_the_backend():
    context = _MixinFirst()
    context._applyPointerCapture(True)
    assert context.captures == [True]
    context._applyPointerCapture(False)
    assert context.captures == [True, False]
