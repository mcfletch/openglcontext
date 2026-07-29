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


class TestAMouseButtonIsAnInputLikeAnyOther:
    """A held mouse button has to be sampleable, or nothing can bind to one.

    In a first-person game the left mouse button is the trigger; everywhere
    else it is a click. Both are "an input that is down right now", so a mouse
    button carries a **name** in the same vocabulary keys use and goes through
    the same sampler — which is what lets a binding list it, a settings page
    present it and a movement mode read it, with no second path for the mouse.
    """

    def button(self, index, state=1):
        from OpenGLContext.events.mouseevents import MouseButtonEvent
        event = MouseButtonEvent()
        event.button = index
        event.state = state
        return event

    def test_a_button_has_a_name(self):
        from OpenGLContext.events import mouseevents
        assert self.button(0).name == mouseevents.button_name(0)

    def test_the_names_of_two_buttons_differ(self):
        assert self.button(0).name != self.button(1).name

    def test_a_button_down_is_held_until_it_comes_up(self):
        state = InputState()
        state.process(self.button(0, 1))
        assert state.held(self.button(0).name)
        state.process(self.button(0, 0))
        assert not state.held(self.button(0).name)

    def test_a_button_press_is_a_one_shot_like_a_key_press(self):
        state = InputState()
        state.process(self.button(1, 1))
        assert state.pressed(self.button(1).name)
        assert not state.pressed(self.button(1).name)

    def test_one_button_does_not_hold_another(self):
        state = InputState()
        state.process(self.button(0, 1))
        assert not state.held(self.button(2).name)

    def test_a_button_and_a_key_are_held_together(self):
        """Firing while walking is the ordinary case, not an edge one."""
        state = InputState()
        state.process(_Event('w', 1))
        state.process(self.button(0, 1))
        assert state.held('w') and state.held(self.button(0).name)

    def test_the_name_reads_as_what_it_is(self):
        from OpenGLContext.events import mouseevents
        assert mouseevents.button_name(0) == '<mouse-0>'


class TestTheSamplerIsFedTheMouseToo:
    """A named button is no use if nothing puts one into the sampler.

    The mix-in that feeds the sampler is where an input becomes *sampled*
    state, and it fed keyboard events only — so a binding naming a mouse
    button matched nothing, silently, for ever.
    """

    def mixin(self):
        from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin

        class _Fed(ViewPlatformMixin):
            def __init__(self):
                self._state = InputState()

            def getInputState(self):
                return self._state

        return _Fed()

    def button(self, index, state=1):
        from OpenGLContext.events.mouseevents import MouseButtonEvent
        event = MouseButtonEvent()
        event.button = index
        event.state = state
        return event

    def test_a_button_press_reaches_the_sampler(self):
        from OpenGLContext.events import mouseevents
        fed = self.mixin()
        fed._recordInput(self.button(0, 1))
        assert fed.getInputState().held(mouseevents.button_name(0))

    def test_and_its_release_reaches_it_as_well(self):
        from OpenGLContext.events import mouseevents
        fed = self.mixin()
        fed._recordInput(self.button(0, 1))
        fed._recordInput(self.button(0, 0))
        assert not fed.getInputState().held(mouseevents.button_name(0))

    def test_the_ordinary_dispatch_records_it(self):
        """Through ProcessEvent, which is what actually runs in a frame.

        `_recordInput` handling a button is no use if the dispatch never hands
        it one, and that seam is invisible from either side alone.
        """
        from OpenGLContext.events import mouseevents
        from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin

        class _Dispatched(ViewPlatformMixin):
            def __init__(self):
                self._state = InputState()

            def getInputState(self):
                return self._state

            def ProcessEvent(self, event):
                return ViewPlatformMixin.ProcessEvent(self, event)

        # The mix-in's ProcessEvent chains to its super's; with nothing else in
        # the way that is object's, so the chain is stubbed rather than run.
        dispatched = _Dispatched()
        try:
            dispatched.ProcessEvent(self.button(0, 1))
        except AttributeError:
            pass                        # no next handler in this bare chain
        assert dispatched.getInputState().held(mouseevents.button_name(0))

    def test_a_wheel_notch_is_never_held(self):
        """A wheel is not a button anybody can hold down, and must not stick."""
        from OpenGLContext.events import mouseevents
        fed = self.mixin()
        fed._recordInput(self.button(mouseevents.WHEEL_UP, 1))
        assert not fed.getInputState().held(
            mouseevents.button_name(mouseevents.WHEEL_UP))


class TestAClickOnAScreenIsNotAnInput:
    """A button the overlay took must not reach the sampler.

    Once a mouse button can be bound to a command — a trigger, say — a click
    on a menu button would otherwise fire the weapon behind it, and a click
    that *dismissed* a panel would leave the button held for as long as it was
    never released into the world.
    """

    def context(self, sinks):
        from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin
        from OpenGLContext.ui.overlay import OverlayMixin

        class _Guarded(OverlayMixin, ViewPlatformMixin):
            def __init__(self):
                self._state = InputState()

            def getInputState(self):
                return self._state

            def overlaySinks(self, event):
                return sinks

        return _Guarded()

    def button(self, index=0, state=1):
        from OpenGLContext.events.mouseevents import MouseButtonEvent
        event = MouseButtonEvent()
        event.button = index
        event.state = state
        return event

    def held(self, guarded):
        from OpenGLContext.events import mouseevents
        return guarded.getInputState().held(mouseevents.button_name(0))

    def test_a_click_the_overlay_took_is_not_recorded(self):
        guarded = self.context(sinks=True)
        assert guarded.ProcessEvent(self.button()) is None
        assert not self.held(guarded)

    def test_a_click_the_overlay_did_not_want_is_recorded(self):
        guarded = self.context(sinks=False)
        try:
            guarded.ProcessEvent(self.button())
        except AttributeError:
            pass                        # no next handler in this bare chain
        assert self.held(guarded)
