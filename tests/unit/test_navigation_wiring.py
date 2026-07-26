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


# -- the sampler is a mouse-move consumer the manager cannot see --------------

class _Optimisable:
    """Enough of a context for the pick optimiser to make its decision."""

    def __init__(self, has_registered_handlers=False):
        self._registered = has_registered_handlers

    def hasMouseMoveHandlers(self):
        return self._registered


class _SamplingContext(_Context, _Optimisable):
    def __init__(self, definition=None):
        _Context.__init__(self, definition)
        _Optimisable.__init__(self, False)


def _fps_definition():
    return ContextDefinition(movementModes=[
        modes.WalkMode(name='walk'), modes.FPSMode(name='fps')])


def test_a_mouse_look_mode_keeps_move_events_alive():
    """The pass drops mouse-moves when 'nobody is listening', but the sampler
    *is* listening -- through ProcessEvent, not through a registered handler.
    Dropped moves leave mouse-look with a zero delta and a view that never
    turns."""
    context = _SamplingContext(_fps_definition())
    navigation = context.getNavigation()
    navigation.select('fps')
    assert context.hasMouseMoveHandlers()


def test_a_mode_that_does_not_steer_leaves_the_optimisation_alone():
    context = _SamplingContext(_fps_definition())
    context.getNavigation().select('walk')
    assert not context.hasMouseMoveHandlers()


def test_a_context_with_no_modes_leaves_the_optimisation_alone():
    assert not _SamplingContext().hasMouseMoveHandlers()


def test_the_pick_optimiser_keeps_a_move_while_mouse_look_is_in_force():
    from OpenGLContext.passes.selection import SelectionMixin
    context = _SamplingContext(_fps_definition())
    context.getNavigation().select('fps')
    optimiser = SelectionMixin.__new__(SelectionMixin)
    optimiser._has_mousemove_handlers = None
    kept = optimiser._optimizePickEvents(context, {('move', (1, 2)): _Move(1, 2)})
    assert len(kept) == 1


def test_mouse_look_turns_the_view_from_a_delivered_move():
    """End to end: two moves in, a turn out."""
    context = _SamplingContext(_fps_definition())
    navigation = context.getNavigation()
    navigation.select('fps')
    turns = []
    context.platform.turn = turns.append
    context.ProcessEvent(_Move(100, 100))
    context.ProcessEvent(_Move(140, 100))
    navigation.update(0.016, context.getInputState())
    assert turns and turns[0] != 0


# -- pointer motion comes from the backend, not from the pick pipeline --------

def test_pointer_motion_reaches_the_sampler_without_a_pick():
    """Mouse-look is not picking.

    Motion delivered as a *pick* event only arrives when the selection buffer
    resolves it, is dropped when the pointer is over nothing, and does not
    arrive at all with picking switched off -- none of which has anything to do
    with turning the view.
    """
    context = _SamplingContext(_fps_definition())
    context.recordPointerMotion(100, 100)
    context.recordPointerMotion(140, 110)
    assert context.getInputState().mouse_delta() == (40, 10)


def test_the_first_motion_only_establishes_where_the_pointer_is():
    """Otherwise entering the window reads as one violent flick of the view."""
    context = _SamplingContext(_fps_definition())
    context.recordPointerMotion(500, 400)
    assert context.getInputState().mouse_delta() == (0.0, 0.0)


def test_direct_motion_stops_the_event_path_double_counting():
    """A backend that reports motion directly also queues a pick event; taking
    the delta from both would turn the view twice as far as the hand moved."""
    context = _SamplingContext(_fps_definition())
    context.recordPointerMotion(100, 100)
    context.recordPointerMotion(140, 100)
    context.ProcessEvent(_Move(200, 100))
    assert context.getInputState().mouse_delta() == (40, 0)


def test_a_backend_that_reports_no_motion_still_uses_the_events():
    """GLUT, pygame and wx deliver moves only as events; they must keep working."""
    context = _SamplingContext(_fps_definition())
    context.ProcessEvent(_Move(100, 100))
    context.ProcessEvent(_Move(160, 100))
    assert context.getInputState().mouse_delta() == (60, 0)


def test_motion_is_sampled_even_with_picking_switched_off():
    definition = _fps_definition()
    definition.pickEnabled = False
    context = _SamplingContext(definition)
    context.recordPointerMotion(10, 10)
    context.recordPointerMotion(30, 10)
    assert context.getInputState().mouse_delta() == (20, 0)


# -- one coordinate convention, measured rather than assumed ------------------

def test_pointer_motion_uses_the_pick_points_origin():
    """Bottom-left, y upward -- the origin every other pointer coordinate in
    the system uses.  The GLFW callback reports y downward and flips it; a
    backend that fed the raw value would invert mouse-look's vertical and
    nothing else, which is the hardest kind of sign error to see."""
    from OpenGLContext.events import glfwevents

    class Backend(glfwevents.EventHandlerMixin):
        def __init__(self):
            self.motions = []
            self.picks = []

        def getViewPort(self):
            return (800, 600)

        def _cursorToFramebuffer(self, window, x, y):
            return x, y

        def recordPointerMotion(self, x, y):
            self.motions.append((x, y))

        def addPickEvent(self, event):
            self.picks.append(event.getPickPoint())

        def triggerPick(self):
            pass

    backend = Backend()
    backend.glfwOnCursorPos(None, 100.0, 150.0)
    assert backend.motions == backend.picks, (
        'the sampler and the pick queue disagree about which way y runs')
    assert backend.motions == [(100, 450)]
