"""The keys every context binds for itself, and the event each is bound on.

`keypress` events are **character input**: GLFW raises them from its character
callback, which fires only when a keystroke produces text.  A binding on
`keypress` for a keystroke that produces no character -- a function key, or a
letter with Alt or Ctrl held -- is accepted, registered, and then never fires,
which is the worst kind of broken because nothing reports it.

So a default binding for a key combination is held to being a ``keyboard``
key-down here, by name.
"""

import pytest

from OpenGLContext.context import Context
from OpenGLContext.events.eventhandlermixin import EventHandlerMixin
from OpenGLContext.events.keyboardevents import KeyboardEvent, KeypressEvent
from OpenGLContext.interactivecontext import InteractiveContext
from OpenGLContext.screenshot import ScreenshotMixin


class Recorder(ScreenshotMixin):
    """Stands in for a context: records what would have been bound.

    The handlers are looked up as bound methods of the context, so this
    borrows the real ones rather than inventing names for them -- which is
    also what lets the test assert *which* method a key runs.
    """

    OnEscape = Context.OnEscape
    OnQuit = Context.OnQuit
    OnFrameRate = Context.OnFrameRate
    OnNextViewpoint = Context.OnNextViewpoint

    def __init__(self):
        self.bound = []

    def addEventHandler(self, type, name='', state=None, modifiers=None,
                        function=None, **named):
        self.bound.append({
            'type': type, 'name': name, 'state': state,
            'modifiers': tuple(modifiers) if modifiers else None,
            'function': function,
        })

    def find(self, name):
        return [entry for entry in self.bound if entry['name'] == name]

    def triggerRedraw(self, force=0):
        pass


@pytest.fixture
def bindings():
    recorder = Recorder()
    Context.setupDefaultEventCallbacks(recorder)
    return recorder


ALT = (False, False, True)


class TestTheDeveloperOverlayKey:
    """Alt+F shows and hides the overlay the frame rate is drawn on."""

    def test_it_is_bound_at_all(self, bindings):
        assert bindings.find('f'), 'nothing brings the developer overlay up'

    def test_it_is_a_key_down_and_not_a_character(self, bindings):
        """Alt + a letter produces no character, so a keypress never arrives."""
        entry = bindings.find('f')[0]
        assert entry['type'] == 'keyboard'
        assert entry['state'] == 1

    def test_alt_is_what_distinguishes_it(self, bindings):
        """Plain `f` is flying, or the next font, in half the demos."""
        assert bindings.find('f')[0]['modifiers'] == ALT

    def test_it_toggles_the_overlay(self, bindings):
        entry = bindings.find('f')[0]
        assert entry['function'].__name__ == 'OnFrameRate'


class TestTheOtherDefaults:
    def test_escape_quits(self, bindings):
        assert bindings.find('<escape>')

    def test_a_screenshot_is_bound(self, bindings):
        """Alt+S and F2 both ask for one; where it goes is test_screenshot.py."""
        assert bindings.find('s')
        assert bindings.find('<F2>')

    def test_nothing_is_bound_on_a_character_that_needs_a_modifier(self,
                                                                   bindings):
        """The rule this file exists for, applied to every default binding."""
        for entry in bindings.bound:
            if entry['type'] == 'keypress' and entry['modifiers']:
                raise AssertionError(
                    '%r is bound on a character that a modifier suppresses'
                    % (entry['name'],))


class Probe(ScreenshotMixin, EventHandlerMixin):
    """The same defaults, registered on real event managers and dispatched into.

    The registration tests above pin the *shape* of the binding; this pins the
    thing that actually matters -- that pressing the key runs the handler --
    through the event manager every backend dispatches into.
    """

    EventManagerClasses = InteractiveContext.EventManagerClasses
    TimeManagerClass = getattr(InteractiveContext, 'TimeManagerClass', None)

    setupDefaultEventCallbacks = Context.setupDefaultEventCallbacks
    OnEscape = Context.OnEscape
    OnQuit = Context.OnQuit
    OnNextViewpoint = Context.OnNextViewpoint
    OnFrameRate = Context.OnFrameRate

    def __init__(self):
        self.toggled = 0
        self.initializeEventManagers()
        self.setupDefaultEventCallbacks()

    def toggleDebugOverlay(self, event=None):
        self.toggled += 1
        return True

    def triggerRedraw(self, force=0):
        pass

    def fire(self, kind, name, modifiers, state=1):
        event = KeyboardEvent() if kind == 'keyboard' else KeypressEvent()
        event.context = self
        event.name = name
        event.modifiers = tuple(modifiers)
        if kind == 'keyboard':
            event.state = state
        self.getEventManager(kind).ProcessEvent(event)


class TestPressingIt:
    @pytest.fixture
    def probe(self):
        return Probe()

    def test_alt_f_brings_the_overlay_up(self, probe):
        probe.fire('keyboard', 'f', (0, 0, 1))
        assert probe.toggled == 1

    def test_a_second_press_takes_it_away_again(self, probe):
        probe.fire('keyboard', 'f', (0, 0, 1))
        probe.fire('keyboard', 'f', (0, 0, 1))
        assert probe.toggled == 2

    def test_plain_f_is_left_for_the_application(self, probe):
        """`f` is flying in the glTF viewer and the next font in another demo."""
        probe.fire('keyboard', 'f', (0, 0, 0))
        assert probe.toggled == 0

    def test_letting_the_key_go_does_not_toggle_it_back(self, probe):
        probe.fire('keyboard', 'f', (0, 0, 1))
        probe.fire('keyboard', 'f', (0, 0, 1), state=0)
        assert probe.toggled == 1

    def test_a_character_event_does_not_toggle_it_a_second_time(self, probe):
        """A backend that does raise one must not double-toggle."""
        probe.fire('keyboard', 'f', (0, 0, 1))
        probe.fire('keypress', 'f', (0, 0, 1))
        assert probe.toggled == 1
