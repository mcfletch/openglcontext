"""What the GLUT window system makes of its callbacks, without opening a window.

GLUT has no relative-motion mode and no focus callback, so both halves of
mouse-look have to be built:

* the pointer is warped back to the middle of the window after every movement,
  which is what makes the motion unbounded -- and the warp arrives back as an
  ordinary movement, which counted would cancel out the movement that provoked
  it and turn the view not at all;
* the pointer *leaving* the window is the nearest thing GLUT has to losing
  focus, and it is the moment after which a held key stops being reported.

See `plans/BACKEND-PARITY.md`.
"""
import pytest

pytest.importorskip('OpenGL.GLUT')

from OpenGL.GLUT import (
    GLUT_ACTIVE_CTRL, GLUT_DOWN, GLUT_LEFT_BUTTON, GLUT_WINDOW_HEIGHT,
    GLUT_WINDOW_WIDTH,
)
from OpenGLContext.context import Context
from OpenGLContext.events.eventhandlermixin import HeldKeyMixin
from OpenGLContext.windowsystem import glut as glutwindowsystem
from OpenGLContext.windowsystem.glut import GLUTWindowSystem

#: The size the stand-in for GLUT reports the window as.
WINDOW = (400, 300)


@pytest.fixture(autouse=True)
def glut(monkeypatch):
    """Answer what the window system asks of GLUT without a window to ask.

    ``glutGetModifiers`` is only legal inside GLUT's own input callback, and
    freeglut says so -- loudly -- when it is called anywhere else.  What is
    under test is what the window system makes of a callback's arguments, so
    the calls that need a live GLUT are answered here, and each warp of the
    pointer is recorded.
    """
    warps = []
    sizes = {GLUT_WINDOW_WIDTH: WINDOW[0], GLUT_WINDOW_HEIGHT: WINDOW[1]}
    monkeypatch.setattr(glutwindowsystem, 'glutGetModifiers', lambda: 0)
    monkeypatch.setattr(glutwindowsystem, 'glutSetWindow', lambda _window: None)
    monkeypatch.setattr(glutwindowsystem, 'glutGet', sizes.__getitem__)
    monkeypatch.setattr(glutwindowsystem, 'glutWarpPointer',
                        lambda x, y: warps.append((x, y)))
    return warps


class _Host(HeldKeyMixin):
    """The part of a context the window system calls, recording what it is told.

    The held-key tracking is the real :class:`HeldKeyMixin`, and a key it
    sends goes back through the window system as a context's does.
    """

    emitKey = Context.emitKey

    def __init__(self, height=WINDOW[1]):
        self.height = height
        self.sampled = []
        self.picked = []
        self.processed = []
        self.forgotten = 0

    def getViewPort(self):
        return (WINDOW[0], self.height)

    def recordPointerMotion(self, x, y):
        self.sampled.append((x, y))

    def forgetPointerOrigin(self):
        self.forgotten += 1

    def addPickEvent(self, event):
        self.picked.append(event)

    def triggerPick(self):
        pass

    def ProcessEvent(self, event):
        self.processed.append(event)


def _windowSystem(height=WINDOW[1], grabbed=False):
    """A GLUT window system over a recording host, its window id 1."""
    host = _Host(height=height)
    system = GLUTWindowSystem(host)
    host.windowsystem = system
    system.window = 1
    system.pointerGrabbed = grabbed
    return system


class TestPointerMotion:
    def test_it_reaches_the_sampler(self):
        system = _windowSystem(height=300)
        system.onMouseMove(100, 40)
        assert system.context.sampled == [(100, 260)]

    def test_y_is_flipped_to_the_pick_point_origin(self):
        """GLUT counts y downward from the top of the window."""
        system = _windowSystem(height=300)
        system.onMouseMove(10, 0)
        assert system.context.sampled == [(10, 300)]

    def test_it_still_goes_to_the_pick_queue(self):
        system = _windowSystem()
        system.onMouseMove(100, 40)
        assert len(system.context.picked) == 1
        assert system.context.picked[0].type == 'mousemove'


class TestTheWarpTheWindowMadeItself:
    def test_the_echo_is_not_a_click_on_anything(self):
        system = _windowSystem(grabbed=True)
        system.pointerWarpedTo = (200, 150)
        system.onMouseMove(200, 150)
        assert system.context.picked == []

    def test_the_echo_does_not_turn_the_view(self):
        """Counted, it is exactly the reverse of the movement that provoked it,
        so the view would stand still however far the hand moved."""
        system = _windowSystem(grabbed=True)
        system.pointerWarpedTo = (200, 150)
        system.onMouseMove(200, 150)
        assert system.context.forgotten == 1, 'the warp was taken as motion'

    def test_a_real_movement_warps_the_pointer_back(self, glut):
        system = _windowSystem(grabbed=True)
        system.onMouseMove(212, 150)
        assert glut == [(WINDOW[0] // 2, WINDOW[1] // 2)]
        assert system.pointerWarpedTo == (WINDOW[0] // 2, WINDOW[1] // 2)

    def test_the_echo_does_not_warp_again(self, glut):
        system = _windowSystem(grabbed=True)
        system.pointerWarpedTo = (200, 150)
        system.onMouseMove(200, 150)
        assert glut == []

    def test_a_pointer_that_is_not_grabbed_is_left_where_it_is(self, glut):
        system = _windowSystem(grabbed=False)
        system.onMouseMove(212, 150)
        assert glut == []

    def test_the_position_is_still_tracked_through_an_echo(self):
        """So the journey is not delivered as one flick when the warp ends."""
        system = _windowSystem(height=300, grabbed=True)
        system.pointerWarpedTo = (200, 150)
        system.onMouseMove(200, 150)
        assert system.context.sampled == [(200, 150)]


class TestHeldKeys:
    def test_a_key_that_goes_down_is_held(self):
        system = _windowSystem()
        system.onKeyDown(b'w', 0, 0)
        assert b'w' in system.context.heldKeys()

    def test_a_key_that_comes_up_is_not(self):
        system = _windowSystem()
        system.onKeyDown(b'w', 0, 0)
        system.onKeyUp(b'w', 0, 0)
        assert system.context.heldKeys() == {}

    def test_a_character_press_is_a_key_press_too(self):
        system = _windowSystem()
        system.onCharacter(b'w', 0, 0)
        assert b'w' in system.context.heldKeys()
        assert [event.type for event in system.context.processed] == [
            'keyboard', 'keypress']

    def test_glut_repeating_a_key_stops_the_synthetic_repeat(self):
        system = _windowSystem()
        system.onKeyDown(b'w', 0, 0)
        assert system.context._nativeRepeat is False  # noqa: SLF001 whether the mixin has seen the platform's own repeat is its internal switch
        system.onKeyDown(b'w', 0, 0)
        assert system.context._nativeRepeat is True  # noqa: SLF001 whether the mixin has seen the platform's own repeat is its internal switch

    def test_the_pointer_leaving_the_window_lets_go_of_held_keys(self):
        system = _windowSystem()
        system.onKeyDown(b'w', 0, 0)
        system.context.processed = []
        system.onEntry(0)
        assert system.context.heldKeys() == {}
        assert [event.state for event in system.context.processed] == [0]

    def test_the_pointer_entering_the_window_keeps_them(self):
        system = _windowSystem()
        system.onKeyDown(b'w', 0, 0)
        system.onEntry(1)
        assert b'w' in system.context.heldKeys()

    def test_a_synthetic_release_carries_the_modifiers_the_press_had(self):
        """A binding that wants ctrl must match on the way up as on the way
        down, or the release never reaches it."""
        system = _windowSystem()
        system.context.noteKeyDown(b'w', GLUT_ACTIVE_CTRL)
        system.context.clearHeldKeys()
        assert len(system.context.processed) == 1
        assert system.context.processed[0].state == 0
        assert system.context.processed[0].getModifiers() == (False, True, False)


class TestMouseButtons:
    def test_a_press_reaches_the_pick_queue(self):
        system = _windowSystem()
        system.onMouseButton(GLUT_LEFT_BUTTON, GLUT_DOWN, 10, 20)
        assert len(system.context.picked) == 1
        assert system.context.picked[0].button == 0
        assert system.context.picked[0].state == 1
