"""Backend-neutral input sampling: what is held *now*, and how far the mouse moved.

A movement mode that reacts to key *events* can only ever do one thing per
event, which is why holding forward and tapping jump has historically dropped
one of the two.  Sampling state per frame is what lets several inputs act at
once.
"""

import pytest

from OpenGLContext.events.inputstate import InputState


class _Event:
    """The shape of the keyboard events every backend already emits."""

    def __init__(self, name, state=1, modifiers=(0, 0, 0)):
        self.name = name
        self.state = state
        self._modifiers = modifiers

    def getModifiers(self):
        return self._modifiers


def test_nothing_is_held_to_begin_with():
    assert not InputState().held('w')


def test_a_key_down_is_held_until_its_key_up():
    state = InputState()
    state.process(_Event('w', state=1))
    assert state.held('w')
    state.process(_Event('w', state=0))
    assert not state.held('w')


def test_several_keys_are_held_at_once():
    """The whole point: moving and jumping are not mutually exclusive."""
    state = InputState()
    for name in ('w', 'a', ' '):
        state.process(_Event(name, state=1))
    assert state.held('w') and state.held('a') and state.held(' ')


def test_held_accepts_several_names_as_alternatives():
    """`w` or the up arrow both mean forward."""
    state = InputState()
    state.process(_Event('<up>', state=1))
    assert state.held('w', '<up>')
    assert not state.held('w', '<down>')


def test_a_repeat_of_a_held_key_does_not_release_it():
    """Key repeat re-sends the down event; it must not toggle."""
    state = InputState()
    state.process(_Event('w', state=1))
    state.process(_Event('w', state=1))
    assert state.held('w')


def test_an_axis_reads_minus_one_to_one():
    state = InputState()
    assert state.axis(('w',), ('s',)) == 0.0
    state.process(_Event('w', state=1))
    assert state.axis(('w',), ('s',)) == 1.0
    state.process(_Event('s', state=1))
    assert state.axis(('w',), ('s',)) == 0.0        # both held cancel
    state.process(_Event('w', state=0))
    assert state.axis(('w',), ('s',)) == -1.0


def test_a_key_press_can_be_consumed_once():
    """A jump should fire on the press, not on every frame the key is down."""
    state = InputState()
    state.process(_Event(' ', state=1))
    assert state.pressed(' ')
    assert not state.pressed(' ')                   # consumed
    state.process(_Event(' ', state=0))
    state.process(_Event(' ', state=1))
    assert state.pressed(' ')                       # a fresh press counts again


def test_a_press_is_remembered_even_if_the_key_is_released_first():
    """A tap inside one frame must not be lost between samples."""
    state = InputState()
    state.process(_Event('x', state=1))
    state.process(_Event('x', state=0))
    assert state.pressed('x')


def test_modifiers_are_whatever_is_held_right_now():
    """The same answer for every key: a modifier is held or it is not."""
    state = InputState()
    state.process(_Event('<up>', state=1, modifiers=(0, 1, 0)))
    assert state.modifiers('<up>') == (0, 1, 0)
    assert state.modifiers('<down>') == (0, 1, 0)


def test_mouse_motion_accumulates_and_is_consumed_by_reading():
    """Mouse-look wants "how far since the last frame", not an absolute point."""
    state = InputState()
    assert state.mouse_delta() == (0.0, 0.0)
    state.mouse_moved(10, 5)
    state.mouse_moved(3, -2)
    assert state.mouse_delta() == (13.0, 3.0)
    assert state.mouse_delta() == (0.0, 0.0)        # consumed


def test_clearing_drops_every_held_key():
    """Focus loss can swallow the key-up, leaving a key stuck down forever."""
    state = InputState()
    state.process(_Event('w', state=1))
    state.mouse_moved(4, 4)
    state.clear()
    assert not state.held('w')
    assert state.mouse_delta() == (0.0, 0.0)


def test_an_event_without_a_state_is_ignored():
    """`keypress` events carry a character but no up/down state."""
    state = InputState()

    class _Bare:
        name = 'q'

    state.process(_Bare())
    assert not state.held('q')


def test_the_held_set_can_be_inspected():
    state = InputState()
    state.process(_Event('w', state=1))
    state.process(_Event('a', state=1))
    assert set(state.held_keys()) == {'w', 'a'}


@pytest.mark.parametrize('name', ['w', 'W', ' ', '<up>', '<F2>'])
def test_key_names_are_taken_as_the_backend_gives_them(name):
    """No case folding: the event system already settled on a spelling, and
    `w` and `W` are different bindings to anyone rebinding keys."""
    state = InputState()
    state.process(_Event(name, state=1))
    assert state.held(name)


class _Key:
    """One keyboard event, as a backend delivers it."""

    type = 'keyboard'

    def __init__(self, name, state, modifiers=(0, 0, 0)):
        self.name = name
        self.state = state
        self._modifiers = modifiers

    def getModifiers(self):
        return self._modifiers


class TestModifiersAreSampledNotRemembered:
    """A held modifier is a thing that is true *now*.

    Recording the modifiers that happened to be down when a key was pressed
    makes ``Ctrl`` + arrow depend on which of the two was pressed first, and
    leaves it applying after Ctrl has been let go.
    """

    def test_a_modifier_pressed_after_the_key_still_counts(self):
        inputs = InputState()
        inputs.process(_Key('<up>', 1, (0, 0, 0)))
        inputs.process(_Key('<control>', 1, (0, 1, 0)))
        assert inputs.modifiers('<up>')[1], "ctrl held but not seen"

    def test_a_modifier_released_while_the_key_is_held_stops_counting(self):
        inputs = InputState()
        inputs.process(_Key('<control>', 1, (0, 1, 0)))
        inputs.process(_Key('<up>', 1, (0, 1, 0)))
        assert inputs.modifiers('<up>')[1]
        inputs.process(_Key('<control>', 0, (0, 0, 0)))
        assert not inputs.modifiers('<up>')[1], "ctrl let go but still applied"

    def test_clearing_forgets_the_modifiers_too(self):
        inputs = InputState()
        inputs.process(_Key('<control>', 1, (0, 1, 0)))
        inputs.clear()
        assert inputs.modifiers('<up>') == (0, 0, 0)

    def test_a_key_up_carries_its_modifiers_too(self):
        inputs = InputState()
        inputs.process(_Key('a', 1, (1, 0, 0)))
        inputs.process(_Key('a', 0, (0, 0, 0)))
        assert inputs.modifiers('a') == (0, 0, 0)


class TestModifiedBindingsFollowTheModifier:
    """The mode's view of the same thing: ctrl+arrow tilts, arrow alone walks."""

    def _mode(self):
        from OpenGLContext.move import modes
        return modes.WalkMode(name='walk')

    def test_ctrl_after_the_arrow_tilts_rather_than_walks(self):
        mode, inputs = self._mode(), InputState()
        inputs.process(_Key('<up>', 1, (0, 0, 0)))
        inputs.process(_Key('<control>', 1, (0, 1, 0)))
        assert mode.active(inputs, 'lookup')
        assert not mode.active(inputs, 'forward')

    def test_letting_ctrl_go_walks_again(self):
        mode, inputs = self._mode(), InputState()
        inputs.process(_Key('<control>', 1, (0, 1, 0)))
        inputs.process(_Key('<up>', 1, (0, 1, 0)))
        assert mode.active(inputs, 'lookup')
        inputs.process(_Key('<control>', 0, (0, 0, 0)))
        assert mode.active(inputs, 'forward')
        assert not mode.active(inputs, 'lookup')
