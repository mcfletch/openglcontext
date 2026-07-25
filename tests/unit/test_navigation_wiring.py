"""A context feeding sampled input, and driving its declared movement modes."""

import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import modes
from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin


class _Key:
    type = 'keyboard'

    def __init__(self, name, state=1):
        self.name, self.state = name, state

    def getModifiers(self):
        return (0, 0, 0)


class _Move:
    type = 'mousemove'

    def __init__(self, x, y):
        self.pickPoint = (x, y)

    def getPickPoint(self):
        return self.pickPoint


class _Platform:
    submerged = False

    def __init__(self):
        self.moved = []
        self.jumped = 0

    def set_move(self, forward=0.0, strafe=0.0, mode='walk'):
        self.moved.append((forward, strafe, mode))

    def set_fly_move(self, forward=0.0, strafe=0.0, up=0.0):
        self.moved.append((forward, strafe, up))

    def jump(self):
        self.jumped += 1

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
    """A context stub: the mixin's input plumbing without a window."""

    drawing = False

    def __init__(self, definition=None):
        self.contextDefinition = definition or ContextDefinition()
        self.platform = _Platform()
        self._redraws = 0

    def getEventManager(self, kind):
        return None

    def triggerRedraw(self, value=1):
        self._redraws += 1


def test_a_context_has_an_input_state():
    assert _Context().getInputState() is not None


def test_the_same_input_state_is_returned_each_time():
    context = _Context()
    assert context.getInputState() is context.getInputState()


def test_keyboard_events_reach_the_input_state():
    """Every backend emits these, so the sampler needs nothing backend-specific."""
    context = _Context()
    context.ProcessEvent(_Key('w', 1))
    assert context.getInputState().held('w')
    context.ProcessEvent(_Key('w', 0))
    assert not context.getInputState().held('w')


def test_mouse_motion_reaches_the_input_state_as_a_delta():
    """Mouse-look wants relative motion; the events carry absolute points."""
    context = _Context()
    context.ProcessEvent(_Move(100, 100))
    context.getInputState().mouse_delta()            # consume the first sample
    context.ProcessEvent(_Move(110, 95))
    assert context.getInputState().mouse_delta() == (10.0, -5.0)


def test_the_first_mouse_event_reports_no_delta():
    """There is nothing to be relative to yet, so a jump to the first position
    must not read as a violent flick of the view."""
    context = _Context()
    context.ProcessEvent(_Move(400, 300))
    assert context.getInputState().mouse_delta() == (0.0, 0.0)


def test_events_still_reach_the_ordinary_dispatch():
    """Feeding the sampler must not swallow the event."""
    seen = []

    class _Watching(_Context):
        def getEventManager(self, kind):
            seen.append(kind)
            return None

    _Watching().ProcessEvent(_Key('w', 1))
    assert seen


def test_a_context_with_no_declared_modes_has_no_navigation_manager():
    """The legacy movement managers keep working untouched."""
    assert _Context().getNavigation() is None


def test_declared_modes_give_the_context_a_navigation_manager():
    definition = ContextDefinition(movementModes=[modes.WalkMode(name='walk')])
    assert _Context(definition).getNavigation() is not None


def test_the_navigation_manager_drives_the_platform_from_held_keys():
    definition = ContextDefinition(movementModes=[modes.WalkMode(name='walk')])
    context = _Context(definition)
    context.ProcessEvent(_Key('w', 1))
    context.ProcessEvent(_Key(' ', 1))
    context.updateNavigation(0.016)
    assert context.platform.moved[-1][0] == pytest.approx(1.0)
    assert context.platform.jumped == 1          # both, in one frame


def test_updating_navigation_without_modes_is_harmless():
    _Context().updateNavigation(0.016)


def test_the_current_mode_is_published_on_the_context_definition():
    walk = modes.WalkMode(name='walk')
    definition = ContextDefinition(movementModes=[walk])
    context = _Context(definition)
    context.updateNavigation(0.016)
    assert definition.movementMode is walk


def test_the_modes_drive_the_view_platform_by_default():
    """A viewer with no character controller still navigates."""
    context = _Context(ContextDefinition(movementModes=[modes.WalkMode(name='walk')]))
    assert context.getNavigationPlatform() is context.platform


def test_a_context_can_name_a_different_thing_for_the_modes_to_drive():
    """A game drives a character controller, not the camera: the camera is
    where the controller ends up."""
    character = _Platform()

    class _Character(_Context):
        def getNavigationPlatform(self):
            return character

    context = _Character(ContextDefinition(
        movementModes=[modes.WalkMode(name='walk')]))
    context.ProcessEvent(_Key('w', 1))
    context.updateNavigation(0.016)
    assert character.moved and not context.platform.moved


def test_the_manager_is_rebuilt_when_what_it_drives_changes():
    """A character controller comes into being when a map loads, which is after
    the context has already been navigating the camera."""
    context = _Context(ContextDefinition(movementModes=[modes.WalkMode(name='walk')]))
    context.updateNavigation(0.016)
    later = _Platform()
    context.getNavigationPlatform = lambda: later
    context.ProcessEvent(_Key('w', 1))
    context.updateNavigation(0.016)
    assert later.moved
