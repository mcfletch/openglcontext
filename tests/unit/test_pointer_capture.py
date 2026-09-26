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

    def set_move(self, forward=0.0, strafe=0.0, mode='walk', speed=None):
        pass

    def set_fly_move(self, forward=0.0, strafe=0.0, up=0.0, speed=None):
        pass

    def jump(self):
        pass

    def turn(self, delta):
        pass

    def look(self, delta):
        pass


class _Dispatch:
    def ProcessEvent(self, _event):
        return None


class _Context(ViewPlatformMixin, _Dispatch):
    """A context stub that records what it was asked to do with the pointer."""

    drawing = False

    def __init__(self, definition=None):
        self.contextDefinition = definition or ContextDefinition()
        self.platform = _Platform()
        self.captures = []

    def getEventManager(self, _kind):
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
                                  modes.FlyMode(name='fly')])
def test_a_mode_steered_by_keys_leaves_the_pointer_alone(mode):
    """Taking the pointer from a mode that has no use for it makes the window
    impossible to leave for no gain."""
    assert not mode.capturePointer


def test_swimming_takes_the_pointer_because_it_steers_with_it():
    """Water must not change how a player points themselves.

    Swimming used to steer with the turn keys like walking does, which meant
    that entering water took a mouse-look player's aim away at the moment they
    could least afford it.  It steers with the pointer now, so it wants the
    pointer.
    """
    assert modes.SwimMode(name='swim').capturePointer


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
    """A window system with no pointer grab must not break the mode that wanted one,
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


# -- the GLFW window system --------------------------------------------------

def _glfwContext(window):
    """A real Context holding a GLFW window system whose window is ``window``

    The grab is asked of the context, as a movement mode asks it, so the call
    has to pass through the context to its window system.
    """
    pytest.importorskip('glfw')
    from OpenGLContext.context import Context  # noqa: PLC0415 the window system needs the glfw package, which the other tests here do not
    from OpenGLContext.windowsystem.glfw import GLFWWindowSystem  # noqa: PLC0415 needs the glfw package, which the other tests here do not
    context = Context.__new__(Context)
    context.windowsystem = GLFWWindowSystem(context)
    context.windowsystem.window = window
    return context


def test_the_glfw_window_system_disables_the_cursor_to_capture(monkeypatch):
    """GLFW's disabled cursor is the one that reports unbounded motion; hidden
    still stops at the screen edge, which is what mouse-look cannot use."""
    context = _glfwContext(object())
    from OpenGLContext.windowsystem import glfw as glfwsystem  # noqa: PLC0415 needs the glfw package, which the other tests here do not
    glfw = glfwsystem.glfw
    calls = []
    monkeypatch.setattr(glfw, 'set_input_mode',
                        lambda _window, mode, value: calls.append((mode, value)))
    monkeypatch.setattr(glfw, 'raw_mouse_motion_supported', lambda: False)
    assert context.setPointerCapture(True)
    assert calls == [(glfw.CURSOR, glfw.CURSOR_DISABLED)]
    assert context.setPointerCapture(False)
    assert calls[-1] == (glfw.CURSOR, glfw.CURSOR_NORMAL)


def test_raw_motion_is_asked_for_when_the_platform_has_it(monkeypatch):
    """Unaccelerated motion is what a view wants; pointer acceleration is a
    desktop convenience that makes a turn depend on how fast it started."""
    context = _glfwContext(object())
    from OpenGLContext.windowsystem import glfw as glfwsystem  # noqa: PLC0415 needs the glfw package, which the other tests here do not
    glfw = glfwsystem.glfw
    calls = []
    monkeypatch.setattr(glfw, 'set_input_mode',
                        lambda _window, mode, value: calls.append((mode, value)))
    monkeypatch.setattr(glfw, 'raw_mouse_motion_supported', lambda: True)
    context.setPointerCapture(True)
    assert (glfw.RAW_MOUSE_MOTION, True) in calls


def test_capturing_without_a_window_is_refused():
    context = _glfwContext(None)
    assert not context.setPointerCapture(True)


# -- the mix-in must not shadow the context's own grab ----------------------

class _Core:
    """A context core that really can grab the pointer, as Context's can."""

    def __init__(self):
        self.captures = []

    def setPointerCapture(self, capture):
        self.captures.append(bool(capture))
        return True

    def hasMouseMoveHandlers(self):
        return False


class _MixinFirst(ViewPlatformMixin, _Core):
    """Ordered as Context is: the mix-in before the core.

    ``Context`` is ``(ViewPlatformMixin, EventHandlerMixin, VRMLSceneMixin,
    ContextCore)``, so a stub on the mix-in would shadow the core's
    implementation, which asks the window system, and mouse-look would never
    grab anything.
    """

    def __init__(self):
        _Core.__init__(self)


def test_the_cores_pointer_grab_is_reached_through_the_mixin():
    context = _MixinFirst()
    assert context.setPointerCapture(True) is True
    assert context.captures == [True]


def test_a_host_with_no_grab_still_reports_that_it_cannot():
    class _NoGrab(ViewPlatformMixin):
        pass

    assert _NoGrab().setPointerCapture(True) is False


def test_a_mouse_look_mode_actually_grabs_through_the_core():
    context = _MixinFirst()
    context._applyPointerCapture(True)  # noqa: SLF001 the grab hook a mouse-look mode drives is this test's subject
    assert context.captures == [True]
    context._applyPointerCapture(False)  # noqa: SLF001 the grab hook a mouse-look mode drives is this test's subject
    assert context.captures == [True, False]


# -- motion while the pointer is on loan -------------------------------------

def test_motion_does_not_steer_the_view_while_the_pointer_is_on_loan():
    """A settings screen is clicked with the same pointer mouse-look holds.

    The window system reports cursor motion directly rather than through the event
    queue, so gating ``ProcessEvent`` -- which is all an overlay can do -- does
    not reach it.  Without this the world keeps turning under the dialog the
    player is trying to read.
    """
    context = _context(modes.FPSMode(name='fps'))
    context.updateNavigation(0.016)
    context.recordPointerMotion(100, 100)
    context.suspendPointerCapture(True)
    context.recordPointerMotion(400, 100)
    assert context.getInputState().mouse_delta() == (0.0, 0.0)


def test_motion_steers_again_once_the_pointer_comes_back():
    context = _context(modes.FPSMode(name='fps'))
    context.updateNavigation(0.016)
    context.recordPointerMotion(100, 100)
    context.suspendPointerCapture(True)
    context.recordPointerMotion(400, 100)
    context.suspendPointerCapture(False)
    context.recordPointerMotion(410, 100)
    assert context.getInputState().mouse_delta()[0] == 10.0


def test_the_view_does_not_jump_when_the_pointer_comes_back():
    """The pointer moved across the dialog; the view must not follow it home."""
    context = _context(modes.FPSMode(name='fps'))
    context.updateNavigation(0.016)
    context.recordPointerMotion(100, 100)
    context.suspendPointerCapture(True)
    for x in range(110, 900, 10):
        context.recordPointerMotion(x, 300)
    context.suspendPointerCapture(False)
    context.recordPointerMotion(890, 300)
    assert context.getInputState().mouse_delta() == (0.0, 0.0)


def test_motion_still_steers_when_nothing_has_asked_for_the_pointer():
    context = _context(modes.FPSMode(name='fps'))
    context.updateNavigation(0.016)
    context.recordPointerMotion(100, 100)
    context.recordPointerMotion(130, 100)
    assert context.getInputState().mouse_delta()[0] == 30.0


# -- motion the window system made itself ------------------------------------

def test_a_pointer_the_window_system_moved_is_not_motion_the_user_made():
    """A window system that warps the pointer has to say so.

    Warping back to the middle of the window is how a window system without an
    unbounded-motion cursor keeps mouse-look turning past the edge of the
    screen, and the warp comes back as an ordinary movement.  Counted, it is
    exactly the reverse of the movement that provoked it, so the view never
    turns at all.
    """
    context = _context(modes.FPSMode(name='fps'))
    context.updateNavigation(0.016)
    context.recordPointerMotion(400, 300)       # the middle of the window
    context.recordPointerMotion(430, 300)       # the hand moves 30px right
    context.forgetPointerOrigin()               # the window system warps back...
    context.recordPointerMotion(400, 300)       # ...and hears about its own warp
    assert context.getInputState().mouse_delta() == (30.0, 0.0)


def test_the_move_after_a_warp_is_measured_from_where_the_pointer_was_put():
    context = _context(modes.FPSMode(name='fps'))
    context.updateNavigation(0.016)
    context.recordPointerMotion(400, 300)
    context.forgetPointerOrigin()
    context.recordPointerMotion(400, 300)
    context.recordPointerMotion(415, 300)
    assert context.getInputState().mouse_delta() == (15.0, 0.0)
