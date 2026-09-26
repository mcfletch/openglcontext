"""Who may switch the movement mode, and what a context binds for it.

``Navigation.modeSwitching`` says how the *user* may change mode: ``keys``
binds :attr:`~OpenGLContext.move.viewplatformmixin.ViewPlatformMixin.movementCycleKey`,
``controls`` puts a :class:`~OpenGLContext.ui.toolpalette.ModeSelector` on the
overlay, and neither leaves switching to the application, whose
``getNavigation().select()`` works whatever the field says.  The classic
navigation is bound where the navigation declares the ``examine`` mode, and a
NULL navigation binds nothing.
"""
import pytest

from OpenGLContext.context import Context
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import modes, smooth
from OpenGLContext.move.navigationdefinition import Navigation
from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import scene_context
from OpenGLContext.ui.overlay import OverlayMixin
from OpenGLContext.ui.toolpalette import ModeSelector


class _Keys(Context):
    """A context whose key bindings are recorded, built with no window."""

    def __init__(self, navigation):
        self.contextDefinition = ContextDefinition(navigation=navigation)
        self.initializeEventManagers()
        self.bound = []
        self.movementManager = None
        self.setupDefaultEventCallbacks()

    def addEventHandler(self, eventType, *arguments, **named):
        self.bound.append((eventType, named.get('name'), named.get('function'),
                           named.get('state')))

    def setMovementManager(self, manager):
        self.movementManager = manager

    def getViewPlatform(self):
        return object()

    def triggerRedraw(self, force=0):
        pass

    def setPointerCapture(self, capture):
        return False


class _Platformed(_Keys):
    """A recorded context that makes its own view platform, as Context does."""

    getViewPlatform = ViewPlatformMixin.getViewPlatform

    def getViewPort(self):
        return (800, 600)


def _keysBound(context, name):
    return [function for kind, key, function, _state in context.bound
            if kind == 'keyboard' and key == name]


class TestTheClassicNavigation:
    def test_it_is_bound_where_the_navigation_declares_examine(self):
        context = _Keys(Navigation(modes=['examine']))
        assert isinstance(context.movementManager, smooth.Smooth)

    def test_a_navigation_without_it_binds_no_classic_keys(self):
        """A game that moves by its own modes alone has no arrow-key camera
        fighting its avatar for the view."""
        context = _Keys(Navigation(modes=['fps', 'fly']))
        assert context.movementManager is None

    def test_null_navigation_still_has_a_view_platform_by_init(self):
        """The render passes draw through it, and ``OnInit`` reaches for
        ``self.platform`` to set a frustum or hand it to a follow camera."""
        context = _Platformed(None)
        assert context.platform is not None

    def test_null_navigation_binds_nothing_to_move_with(self):
        context = _Keys(None)
        assert context.movementManager is None
        assert not _keysBound(context, context.movementCycleKey)


class TestSwitchingByKey:
    def test_no_switching_leaves_the_cycle_key_unbound(self):
        context = _Keys(Navigation(modes=['walk', 'fly']))
        assert not _keysBound(context, context.movementCycleKey)

    def test_the_application_can_still_select_a_mode(self):
        """The field governs what the user is offered, never the application."""
        context = _Keys(Navigation(modes=['walk', 'fly']))
        navigation = context.getNavigation()
        assert navigation.select('fly')
        assert context.contextDefinition.navigation.current.name == 'fly'

    def test_keys_binds_the_cycle_key(self):
        context = _Keys(Navigation(modes=['walk', 'fly'], modeSwitching=['keys']))
        bound = _keysBound(context, context.movementCycleKey)
        assert bound and bound[-1] == context.cycleMovementMode

    def test_the_cycle_key_fires_on_the_release(self):
        context = _Keys(Navigation(modes=['walk', 'fly'], modeSwitching=['keys']))
        assert [state for _kind, key, _function, state in context.bound
                if key == context.movementCycleKey] == [0]

    def test_the_cycle_key_steps_to_the_next_mode(self):
        context = _Keys(Navigation(modes=['walk', 'fly'], modeSwitching=['keys']))
        assert context.cycleMovementMode().name == 'fly'
        assert context.cycleMovementMode().name == 'walk'

    def test_a_world_imposed_mode_applies_with_switching_empty(self):
        class Platform:
            submerged = True

            def set_fly_move(self, **named):
                pass

            def set_swim_move(self, **named):
                pass

            def turn(self, angle):
                pass

            def look(self, angle):
                pass

        context = _Keys(Navigation(modes=['walk', 'swim']))
        context.getNavigationPlatform = lambda: Platform()
        context.updateNavigation(0.016)
        assert context.contextDefinition.navigation.current.name == 'swim'


class _Selecting:
    """What a selector reads: a navigation manager's modes, and select()"""

    def __init__(self, names):
        self.modes = [modes.WalkMode(name=name) for name in names]
        self.current = self.modes[0]

    def selectable(self):
        return list(self.modes)

    def select(self, name):
        for mode in self.modes:
            if mode.name == name:
                self.current = mode
                return True
        return False


class TestTheModeSelector:
    def test_it_offers_each_selectable_mode(self):
        navigation = _Selecting(['walk', 'fly', 'fps'])
        selector = ModeSelector(navigation=lambda: navigation)
        assert [str(button.tool) for button in selector.buttons()] == [
            'walk', 'fly', 'fps']

    def test_the_mode_in_force_is_lit(self):
        navigation = _Selecting(['walk', 'fly'])
        selector = ModeSelector(navigation=lambda: navigation)
        lit = [str(button.tool) for button in selector.buttons() if button.active()]
        assert lit == ['walk']

    def test_a_click_selects_the_mode(self):
        navigation = _Selecting(['walk', 'fly'])
        selector = ModeSelector(navigation=lambda: navigation)
        selector.buttons()[1].activate()
        assert navigation.current.name == 'fly'

    def test_no_navigation_yet_offers_nothing(self):
        """A viewer declares its modes when a scene loads; until then there is
        nothing to choose between."""
        assert ModeSelector(navigation=lambda: None).buttons() == []

    def test_it_follows_modes_declared_later(self):
        navigation = _Selecting(['walk'])
        selector = ModeSelector(navigation=lambda: navigation)
        navigation.modes.append(modes.FlyMode(name='fly'))
        selector.refresh()
        assert [str(button.tool) for button in selector.buttons()] == ['walk', 'fly']


class _Overlaid(OverlayMixin, Context):
    pass


@pytest.fixture
def core_profile():
    """Skip where this machine opens no core-profile context."""
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


class TestOnScreenControls:
    def test_controls_need_the_overlay(self, core_profile):
        """Raised as the context is built, naming what to mix in, rather than
        leaving a declaration that silently offers nothing."""
        with pytest.raises(TypeError, match='OverlayMixin'):
            with scene_context([], navigation=Navigation(
                    modes=['walk', 'fly'], modeSwitching=['controls'])):
                pass

    def test_an_overlaid_context_puts_the_selector_up(self, core_profile):
        with scene_context([], base=_Overlaid, navigation=Navigation(
                modes=['walk', 'fly'], modeSwitching=['controls'])) as context:
            selectors = [panel for panel in context.overlays.panels
                         if isinstance(panel, ModeSelector)]
        assert len(selectors) == 1
