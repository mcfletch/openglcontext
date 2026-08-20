"""Record a session through the engine's own input plumbing, then run it again.

The unit tests either side of this pin the recorder's rules and the replay's
arithmetic.  This one pins the thing they are for: real engine events, through
the real movement mixin, into a file -- and a second context, given nothing but
that file, arriving in the same state a frame at a time.

No GL is needed for it, because none of the machinery in question is GL: the
events, the sampler and the movement modes are all the engine, and a window
would only make the test slower and less able to say which frame something
happened on.
"""

import pytest

from OpenGLContext import telemetry
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.events.keyboardevents import KeyboardEvent
from OpenGLContext.events.mouseevents import MouseButtonEvent
from OpenGLContext.move import modes
from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin


class _Platform:
    submerged = False

    def __init__(self):
        self.moved = []

    def set_move(self, forward=0.0, strafe=0.0, mode='walk', speed=None):
        self.moved.append((forward, strafe, mode))

    def set_fly_move(self, forward=0.0, strafe=0.0, up=0.0, speed=None):
        self.moved.append((forward, strafe, up))

    def jump(self):
        pass

    def turn(self, delta):
        pass

    def look(self, delta):
        pass


class _Dispatch:
    """Stands in for the event-handler mixin below ViewPlatformMixin."""

    def ProcessEvent(self, event):
        manager = self.getEventManager(getattr(event, 'type', None))
        return manager.ProcessEvent(event) if manager else None


class _Context(ViewPlatformMixin, _Dispatch):
    """The mixin's input plumbing, with a frame you can call by hand."""

    drawing = False

    def __init__(self, definition=None):
        self.contextDefinition = definition or _walking()
        self.platform = _Platform()
        self.telemetry = None
        self.frames = 0
        #: What was held, and how far the pointer moved, on each frame.
        self.samples = []
        self.picked = []

    def getEventManager(self, kind):
        return None

    def triggerRedraw(self, value=1):
        pass

    def triggerPick(self):
        pass

    def addPickEvent(self, event):
        self.picked.append(event)

    def OnDraw(self, force=1):
        """One frame: sample what is held, exactly as a movement mode would."""
        state = self.getInputState()
        self.samples.append((sorted(state.held_keys()), state.mouse_delta()))
        self.frames += 1
        return 1


def _walking():
    return ContextDefinition(movementModes=[modes.WalkMode(name='walk')])


def _key(name, state):
    event = KeyboardEvent()
    event.name, event.state = name, state
    return event


def _click(button, state, x, y):
    event = MouseButtonEvent()
    event.button, event.state = button, state
    event.pickPoint = (float(x), float(y))
    return event


def _play(context):
    """A little session: walk forward, look right, shoot, stop."""
    context.ProcessEvent(_key('w', 1))
    context.recordPointerMotion(400, 300)
    context.OnDraw()

    for x in range(410, 450, 10):                  # a smooth flick of the mouse
        context.recordPointerMotion(x, 300)
    context.OnDraw()

    context.addPickEvent(_click(0, 1, 440, 300))
    context.OnDraw()

    context.ProcessEvent(_key('w', 0))
    context.addPickEvent(_click(0, 0, 440, 300))
    context.OnDraw()


@pytest.fixture
def recorded(tmp_path):
    context = _Context()
    session = telemetry.start(context, tmp_path / 'session.jsonl')
    _play(context)
    session.close()
    return context, tmp_path / 'session.jsonl'


def test_a_replayed_session_holds_the_same_keys_on_the_same_frames(recorded):
    original, path = recorded
    playing = _Context()
    driver = telemetry.start_replay(playing, path)
    try:
        for _ in range(original.frames):
            playing.OnDraw()
    finally:
        driver.close()
    assert [held for held, _delta in playing.samples] == [
        held for held, _delta in original.samples]


def test_the_view_turns_by_the_same_amount_it_turned(recorded):
    """The pointer moved four times inside one frame; only the total is
    observable, and the total is what has to come back."""
    original, path = recorded
    playing = _Context()
    driver = telemetry.start_replay(playing, path)
    try:
        for _ in range(original.frames):
            playing.OnDraw()
    finally:
        driver.close()
    assert [delta for _held, delta in playing.samples] == [
        delta for _held, delta in original.samples]


def test_the_click_comes_back_where_it_was_clicked(recorded):
    original, path = recorded
    playing = _Context()
    driver = telemetry.start_replay(playing, path)
    try:
        for _ in range(original.frames):
            playing.OnDraw()
    finally:
        driver.close()
    assert [(event.button, event.state, event.getPickPoint())
            for event in playing.picked] == [
        (event.button, event.state, event.getPickPoint())
        for event in original.picked]


def test_a_replay_leaves_the_recording_alone(recorded):
    """Two replays of one file must agree, which they cannot if the first
    consumed it."""
    _original, path = recorded
    runs = []
    for _ in range(2):
        playing = _Context()
        driver = telemetry.start_replay(playing, path)
        try:
            for _ in range(8):
                playing.OnDraw()
        finally:
            driver.close()
        runs.append(playing.samples)
    assert runs[0] == runs[1]


def test_the_session_reads_back_as_a_report(recorded):
    from OpenGLContext.telemetry import report
    from OpenGLContext.telemetry.replay import Recording

    _original, path = recorded
    found = report.describe(Recording.read(path), events=True)
    assert 'keyboard' in found
    assert 'mousebutton' in found
    assert '4 frames' in found


class TestASessionThatDependsOnItsLuck:
    """Input alone does not replay a game whose world, loot or bots come out
    of a generator: the same keys against a different sequence of numbers give
    a different game."""

    def _rolls(self, path, replaying=False):
        import random

        from OpenGLContext import entropy, telemetry

        context = _Context()
        rolled = []

        def roll(force=1):
            rolled.append(random.random())
            rolled.append(float(entropy.generator('loot').random()))
            return 1

        context.OnDraw = roll
        if replaying:
            session = telemetry.start_replay(context, path)
        else:
            session = telemetry.start(context, path)
        try:
            for _ in range(5):
                context.OnDraw()
        finally:
            session.close()
        return rolled

    def test_the_same_numbers_come_up(self, tmp_path):
        import random

        from OpenGLContext import entropy

        path = tmp_path / 'session.jsonl'
        recorded = self._rolls(path)

        random.seed(0)                          # somewhere else entirely
        entropy.reseed(1)
        assert self._rolls(path, replaying=True) == recorded

    def test_and_they_are_not_the_same_numbers_by_accident(self, tmp_path):
        """Without the recording they would differ, which is what makes the
        test above mean something."""
        import random

        from OpenGLContext import entropy

        path = tmp_path / 'session.jsonl'
        recorded = self._rolls(path)
        random.seed(0)
        entropy.reseed(1)
        assert self._rolls(tmp_path / 'other.jsonl') != recorded
