"""An input event as a plain record, and back again.

Three things need the same vocabulary: the telemetry recorder writing input
down, the replay putting it back, and the test event injector, which had a JSON
spelling of its own.  These pin the round trip and the delivery, so a record
written by one is understood by the others.
"""

import pytest

from OpenGLContext.events import synthetic
from OpenGLContext.events.keyboardevents import KeyboardEvent, KeypressEvent
from OpenGLContext.events.mouseevents import MouseButtonEvent, MouseMoveEvent


class TestDescribe:
    def test_a_key_keeps_its_name_state_and_modifiers(self):
        event = KeyboardEvent()
        event.name = 'w'
        event.state = 1
        event.modifiers = (0, 1, 0)
        assert synthetic.describe(event) == {
            'type': 'keyboard', 'key': 'w', 'state': 1, 'modifiers': [0, 1, 0]}

    def test_a_character_has_no_state_because_it_is_not_a_transition(self):
        event = KeypressEvent()
        event.name = 'W'
        found = synthetic.describe(event)
        assert found['type'] == 'keypress'
        assert 'state' not in found

    def test_a_button_carries_where_it_was_clicked(self):
        event = MouseButtonEvent()
        event.button = 2
        event.state = 1
        event.pickPoint = (13.0, 47.0)
        found = synthetic.describe(event)
        assert (found['button'], found['state']) == (2, 1)
        assert (found['x'], found['y']) == (13.0, 47.0)

    def test_a_move_carries_the_buttons_held_during_it(self):
        event = MouseMoveEvent()
        event.buttons = (0, 2)
        event.pickPoint = (1.0, 2.0)
        assert synthetic.describe(event)['buttons'] == [0, 2]

    def test_an_event_it_does_not_know_is_not_invented(self):
        class Odd:
            type = 'something-else'
        assert synthetic.describe(Odd()) is None


class TestRoundTrip:
    """``build(describe(event))`` is the same event, because a replay is only
    as good as the fidelity of this pair."""

    @pytest.mark.parametrize('make', [
        lambda: _key('w', 1, (1, 0, 0)),
        lambda: _press('W', (1, 0, 0)),
        lambda: _button(0, 1, 100, 200, (0, 0, 1)),
        lambda: _move((0,), 30, 40, (0, 0, 0)),
    ])
    def test_what_goes_in_comes_out(self, make):
        original = make()
        rebuilt = synthetic.build(synthetic.describe(original))
        assert synthetic.describe(rebuilt) == synthetic.describe(original)

    def test_the_rebuilt_event_is_of_the_original_class(self):
        rebuilt = synthetic.build(synthetic.describe(_button(1, 0, 5, 6, (0, 0, 0))))
        assert isinstance(rebuilt, MouseButtonEvent)

    def test_a_record_naming_nothing_buildable_answers_none(self):
        assert synthetic.build({'type': 'pointer', 'x': 1, 'y': 2}) is None


class FakeContext:
    """Just the entry points a platform calls, remembering what arrived."""

    def __init__(self):
        self.processed = []
        self.picked = []
        self.picks = 0
        self.pointer = []
        self.forgot = 0
        self.resized = []

    def ProcessEvent(self, event):
        self.processed.append(event)

    def addPickEvent(self, event):
        self.picked.append(event)

    def triggerPick(self):
        self.picks += 1

    def recordPointerMotion(self, x, y):
        self.pointer.append((x, y))

    def forgetPointerOrigin(self):
        self.forgot += 1

    def OnResize(self, width, height):
        self.resized.append((width, height))


class TestDispatch:
    def test_a_key_goes_through_the_context_the_platform_would_have_used(self):
        context = FakeContext()
        synthetic.dispatch(context, {'type': 'keyboard', 'key': 'a', 'state': 1})
        assert len(context.processed) == 1
        assert context.processed[0].name == 'a'
        assert context.processed[0].context is context

    def test_a_click_goes_through_the_selection_pass_when_it_did_originally(self):
        context = FakeContext()
        synthetic.dispatch(context, {'type': 'mousebutton', 'button': 0,
                                     'state': 1, 'x': 4, 'y': 5, 'pick': True})
        assert len(context.picked) == 1
        assert context.picks == 1
        assert not context.processed

    def test_without_a_pick_it_reaches_the_manager_directly(self):
        """The injector's cheaper route: no render, context-level handlers only."""
        context = FakeContext()
        seen = []
        context.getEventManager = lambda kind: _Manager(seen)
        synthetic.dispatch(context, {'type': 'mousebutton', 'button': 0,
                                     'state': 1, 'x': 4, 'y': 5})
        assert len(seen) == 1
        assert seen[0].getObjectPaths() == []
        assert not context.picked

    def test_pointer_motion_goes_to_the_sampler_not_the_queue(self):
        context = FakeContext()
        synthetic.dispatch(context, {'type': 'pointer', 'x': 7, 'y': 9})
        assert context.pointer == [(7, 9)]
        assert not context.picked

    def test_forgetting_the_origin_is_a_record_of_its_own(self):
        """A backend that warps the pointer says so, or the replay flicks."""
        context = FakeContext()
        synthetic.dispatch(context, {'type': 'pointer-origin'})
        assert context.forgot == 1

    def test_a_resize_reaches_onresize(self):
        context = FakeContext()
        synthetic.dispatch(context, {'type': 'resize', 'width': 32, 'height': 16})
        assert context.resized == [(32, 16)]

    def test_a_context_missing_an_entry_point_is_skipped_rather_than_fatal(self):
        """A minimal context has no pointer sampler; a replay must survive it."""
        class Bare:
            pass
        assert synthetic.dispatch(Bare(), {'type': 'pointer', 'x': 1, 'y': 2}) is False

    def test_an_unknown_record_is_refused_rather_than_guessed(self):
        assert synthetic.dispatch(FakeContext(), {'type': 'nonsense'}) is False


class _Manager:
    def __init__(self, seen):
        self.seen = seen

    def ProcessEvent(self, event):
        self.seen.append(event)


def _key(name, state, modifiers):
    event = KeyboardEvent()
    event.name, event.state, event.modifiers = name, state, modifiers
    return event


def _press(name, modifiers):
    event = KeypressEvent()
    event.name, event.modifiers = name, modifiers
    return event


def _button(button, state, x, y, modifiers):
    event = MouseButtonEvent()
    event.button, event.state, event.modifiers = button, state, modifiers
    event.pickPoint = (float(x), float(y))
    return event


def _move(buttons, x, y, modifiers):
    event = MouseMoveEvent()
    event.buttons, event.modifiers = buttons, modifiers
    event.pickPoint = (float(x), float(y))
    return event


class TestWhatAContextCannotTake:
    """A replay reaches whatever context the game happens to have, and one
    input it cannot place must not end the session."""

    def test_a_pick_with_nowhere_to_queue_it_is_refused(self):
        class Bare:
            pass
        assert synthetic.dispatch(Bare(), {'type': 'mousebutton', 'button': 0,
                                           'state': 1, 'pick': True}) is False

    def test_a_direct_delivery_with_no_manager_is_refused(self):
        context = FakeContext()
        context.getEventManager = lambda kind: None
        assert synthetic.dispatch(
            context, {'type': 'mousemove', 'x': 1, 'y': 2}) is False
