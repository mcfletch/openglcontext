"""What the pygame window system makes of SDL's input, without opening a window.

The two things that decide whether mouse-look works at all under pygame:

* **Motion has to reach the sampler as it happens.** A move delivered as a
  *pick* event arrives only once the selection buffer has resolved it, is
  dropped when the pointer is over nothing, and never arrives with picking off
  -- so a mode that grabbed the pointer turned the view not at all.
* **A grabbed pointer stops moving.** SDL's relative mode is what reports
  unbounded motion, and in it the position no longer changes while the deltas
  do; the sampler works in positions and takes the difference itself, so the
  deltas have to be walked back into one.

See `plans/BACKEND-PARITY.md`.
"""
import pytest

pygame = pytest.importorskip('pygame')

from OpenGLContext.context import Context
from OpenGLContext.events.eventhandlermixin import HeldKeyMixin
from OpenGLContext.windowsystem.pygame import PygameWindowSystem


@pytest.fixture(autouse=True)
def sdl(monkeypatch):
    """SDL's keyboard state needs its video system up, and nothing more.

    The dummy driver brings that up with no display of any kind, which is all
    these need: what is under test is what the window system makes of an
    event, not anything a window does.
    """
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    pygame.display.init()
    try:
        yield pygame
    finally:
        pygame.display.quit()


class _Motion:
    """One SDL MOUSEMOTION, as pygame hands it over."""

    def __init__(self, pos, rel=(0, 0)):
        self.pos, self.rel = pos, rel


class _Host(HeldKeyMixin):
    """The part of a context the window system calls, recording what it is told.

    The held-key tracking is the real :class:`HeldKeyMixin`, and a key it
    sends goes back through the window system as a context's does.
    """

    emitKey = Context.emitKey

    def __init__(self, height=300):
        self.height = height
        self.sampled = []
        self.picked = []
        self.processed = []

    def getViewPort(self):
        return (400, self.height)

    def recordPointerMotion(self, x, y):
        self.sampled.append((x, y))

    def addPickEvent(self, event):
        self.picked.append(event)

    def triggerPick(self):
        pass

    def ProcessEvent(self, event):
        self.processed.append(event)


def _windowSystem(height=300):
    """A pygame window system over a recording host."""
    host = _Host(height=height)
    system = PygameWindowSystem(host)
    host.windowsystem = system
    return system


class TestPointerMotion:
    def test_it_reaches_the_sampler(self):
        system = _windowSystem()
        system.onMouseMotion(_Motion((100, 40), (5, -5)))
        assert system.context.sampled == [(100, 260)]

    def test_y_is_flipped_to_the_pick_point_origin(self):
        """SDL counts y downward from the top; everything downstream of the
        context counts it upward from the bottom."""
        system = _windowSystem(height=300)
        system.onMouseMotion(_Motion((10, 0)))
        assert system.context.sampled == [(10, 300)]

    def test_it_still_goes_to_the_pick_queue(self):
        system = _windowSystem()
        system.onMouseMotion(_Motion((100, 40)))
        assert len(system.context.picked) == 1
        assert system.context.picked[0].type == 'mousemove'


class TestAGrabbedPointer:
    """In relative mode the position stops changing and only the deltas move."""

    def test_the_deltas_are_walked_into_a_position(self):
        system = _windowSystem(height=300)
        system.pointerGrabbed = True
        system.onMouseMotion(_Motion((200, 150), (10, 0)))
        system.onMouseMotion(_Motion((200, 150), (10, 0)))
        assert system.context.sampled == [(210, 150), (220, 150)]

    def test_a_downward_delta_is_a_downward_move(self):
        system = _windowSystem(height=300)
        system.pointerGrabbed = True
        system.onMouseMotion(_Motion((200, 150), (0, 20)))
        assert system.context.sampled == [(200, 130)]

    def test_letting_go_goes_back_to_the_reported_position(self):
        system = _windowSystem(height=300)
        system.pointerGrabbed = True
        system.onMouseMotion(_Motion((200, 150), (10, 0)))
        system.pointerGrabbed = False
        system.onMouseMotion(_Motion((30, 40), (0, 0)))
        assert system.context.sampled[-1] == (30, 260)

    def test_taking_hold_again_starts_from_where_the_pointer_is(self):
        system = _windowSystem(height=300)
        system.pointerGrabbed = True
        system.onMouseMotion(_Motion((200, 150), (10, 0)))
        system.pointerGrabbed = False
        system.onMouseMotion(_Motion((30, 40)))
        system.pointerGrabbed = True
        system.onMouseMotion(_Motion((30, 40), (5, 0)))
        assert system.context.sampled[-1] == (35, 260)

    def test_a_report_with_no_delta_is_still_a_position(self):
        system = _windowSystem(height=300)
        system.pointerGrabbed = True
        system.onMouseMotion(_Motion((200, 150), (0, 0)))
        assert system.context.sampled == [(200, 150)]


class _Key:
    def __init__(self, key, unicode=''):
        self.key, self.unicode = key, unicode


class TestHeldKeys:
    def test_a_key_that_goes_down_is_held(self):
        system = _windowSystem()
        system.onKeyDown(_Key(pygame.K_w, 'w'))
        assert pygame.K_w in system.context.heldKeys()

    def test_a_key_that_comes_up_is_not(self):
        system = _windowSystem()
        system.onKeyDown(_Key(pygame.K_w, 'w'))
        system.onKeyUp(_Key(pygame.K_w))
        assert system.context.heldKeys() == {}

    def test_losing_focus_sends_the_release_sdl_never_will(self):
        system = _windowSystem()
        system.onKeyDown(_Key(pygame.K_w, 'w'))
        system.context.processed = []
        system.onWindowFocusLost(None)
        released = [event for event in system.context.processed
                    if event.type == 'keyboard' and event.state == 0]
        assert len(released) == 1
        assert released[0].name == 'w'
        assert system.context.heldKeys() == {}

    def test_sdl_repeating_a_key_stops_the_synthetic_repeat(self):
        """`pygame.key.set_repeat` is on, so a second down for a key already
        held is SDL's own repeat and must not be doubled."""
        system = _windowSystem()
        system.onKeyDown(_Key(pygame.K_w, 'w'))
        assert system.context._nativeRepeat is False
        system.onKeyDown(_Key(pygame.K_w, 'w'))
        assert system.context._nativeRepeat is True
        system.context.processed = []
        system.context.pumpKeyRepeats(now=1e9)
        assert system.context.processed == []
