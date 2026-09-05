"""What the GLUT backend makes of its callbacks, without opening a window.

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

from OpenGL.GLUT import GLUT_ACTIVE_CTRL, GLUT_DOWN, GLUT_LEFT_BUTTON  # noqa: E402
from OpenGLContext.events import glutevents                            # noqa: E402


@pytest.fixture(autouse=True)
def modifiers(monkeypatch):
    """Answer the modifier state without a window to read it from.

    ``glutGetModifiers`` is only legal inside GLUT's own input callback, and
    freeglut says so -- loudly -- when it is called anywhere else. What is
    under test is what the mix-in makes of a callback's arguments, so the one
    call that needs a live GLUT is answered here.
    """
    monkeypatch.setattr(glutevents, 'glutGetModifiers', lambda: 0)


class _Handler(glutevents.EventHandlerMixin):
    """The mix-in with the little of a window it reaches for."""

    def __init__(self, height=300):
        self.height = height
        self.sampled = []
        self.picked = []
        self.processed = []
        self.forgotten = 0
        self.recentred = 0
        self.warpedTo = None

    def getViewPort(self):
        return (400, self.height)

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

    # What GLUTContext supplies; see its own pointer capture.
    def recentrePointer(self):
        self.recentred += 1

    def pointerWarpEcho(self, x, y):
        if self.warpedTo == (int(x), int(y)):
            self.warpedTo = None
            return True
        return False


class TestPointerMotion:
    def test_it_reaches_the_sampler(self):
        handler = _Handler(height=300)
        handler.glutOnMouseMove(100, 40)
        assert handler.sampled == [(100, 260)]

    def test_y_is_flipped_to_the_pick_point_origin(self):
        """GLUT counts y downward from the top of the window."""
        handler = _Handler(height=300)
        handler.glutOnMouseMove(10, 0)
        assert handler.sampled == [(10, 300)]

    def test_it_still_goes_to_the_pick_queue(self):
        handler = _Handler()
        handler.glutOnMouseMove(100, 40)
        assert len(handler.picked) == 1
        assert handler.picked[0].type == 'mousemove'

    def test_a_context_with_no_sampler_is_no_error(self):
        class _Bare(_Handler):
            recordPointerMotion = None

        handler = _Bare()
        handler.glutOnMouseMove(100, 40)
        assert len(handler.picked) == 1


class TestTheWarpTheWindowMadeItself:
    def test_the_echo_is_not_a_click_on_anything(self):
        handler = _Handler()
        handler.warpedTo = (200, 150)
        handler.glutOnMouseMove(200, 150)
        assert handler.picked == []

    def test_the_echo_does_not_turn_the_view(self):
        """Counted, it is exactly the reverse of the movement that provoked it,
        so the view would stand still however far the hand moved."""
        handler = _Handler()
        handler.warpedTo = (200, 150)
        handler.glutOnMouseMove(200, 150)
        assert handler.forgotten == 1, 'the warp was taken as motion'

    def test_a_real_movement_warps_the_pointer_back(self):
        handler = _Handler()
        handler.glutOnMouseMove(212, 150)
        assert handler.recentred == 1

    def test_the_echo_does_not_warp_again(self):
        handler = _Handler()
        handler.warpedTo = (200, 150)
        handler.glutOnMouseMove(200, 150)
        assert handler.recentred == 0

    def test_the_position_is_still_tracked_through_an_echo(self):
        """So the journey is not delivered as one flick when the warp ends."""
        handler = _Handler(height=300)
        handler.warpedTo = (200, 150)
        handler.glutOnMouseMove(200, 150)
        assert handler.sampled == [(200, 150)]


class TestHeldKeys:
    def test_a_key_that_goes_down_is_held(self):
        handler = _Handler()
        handler.glutOnKeyDown(b'w', 0, 0)
        assert b'w' in handler.heldKeys()

    def test_a_key_that_comes_up_is_not(self):
        handler = _Handler()
        handler.glutOnKeyDown(b'w', 0, 0)
        handler.glutOnKeyUp(b'w', 0, 0)
        assert handler.heldKeys() == {}

    def test_a_character_press_is_a_key_press_too(self):
        handler = _Handler()
        handler.glutOnCharacter(b'w', 0, 0)
        assert b'w' in handler.heldKeys()
        assert [event.type for event in handler.processed] == [
            'keyboard', 'keypress']

    def test_glut_repeating_a_key_stops_the_synthetic_repeat(self):
        handler = _Handler()
        handler.glutOnKeyDown(b'w', 0, 0)
        assert handler._nativeRepeat is False
        handler.glutOnKeyDown(b'w', 0, 0)
        assert handler._nativeRepeat is True

    def test_a_synthetic_release_carries_the_modifiers_the_press_had(self):
        """A binding that wants ctrl must match on the way up as on the way
        down, or the release never reaches it."""
        handler = _Handler()
        handler.noteKeyDown(b'w', GLUT_ACTIVE_CTRL)
        handler.processed = []
        handler.clearHeldKeys()
        assert len(handler.processed) == 1
        assert handler.processed[0].state == 0
        assert handler.processed[0].getModifiers() == (False, True, False)


class TestMouseButtons:
    def test_a_press_reaches_the_pick_queue(self):
        handler = _Handler()
        handler.glutOnMouseButton(GLUT_LEFT_BUTTON, GLUT_DOWN, 10, 20)
        assert len(handler.picked) == 1
        assert handler.picked[0].button == 0
        assert handler.picked[0].state == 1
