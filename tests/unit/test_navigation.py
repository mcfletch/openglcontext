"""Declaring movement modes on a context, and switching between them."""

import pytest
from vrml import protofunctions

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.events.inputstate import InputState
from OpenGLContext.move import modes
from OpenGLContext.move.navigation import NavigationManager


class _Platform:
    def __init__(self):
        self.submerged = False
        self.moved = []
        self.jumped = 0

    def set_move(self, forward=0.0, strafe=0.0, mode='walk'):
        self.moved.append(('walk', forward, strafe, mode))

    def set_fly_move(self, forward=0.0, strafe=0.0, up=0.0):
        self.moved.append(('fly', forward, strafe, up))

    def jump(self):
        self.jumped += 1

    def turn(self, delta):
        pass

    def look(self, delta):
        pass


def _manager(*mode_nodes, platform=None):
    definition = ContextDefinition(movementModes=list(mode_nodes))
    return NavigationManager(definition, platform or _Platform()), definition


# -- declaring modes on the context ------------------------------------------

def test_a_context_definition_carries_its_movement_modes():
    walk, fly = modes.WalkMode(name='walk'), modes.FlyMode(name='fly')
    definition = ContextDefinition(movementModes=[walk, fly])
    assert list(definition.movementModes) == [walk, fly]


def test_a_context_definition_has_no_modes_by_default():
    assert list(ContextDefinition().movementModes) == []


def test_the_current_mode_is_a_field_on_the_context_definition():
    walk = modes.WalkMode(name='walk')
    manager, definition = _manager(walk)
    manager.select('walk')
    assert definition.movementMode is walk


def test_the_current_mode_can_be_watched_for_change():
    """So a game can react to entering water — an overlay, a sound, a filter —
    without the navigation manager knowing anything about it."""
    walk, swim = modes.WalkMode(name='walk'), modes.SwimMode(name='swim')
    platform = _Platform()
    manager, definition = _manager(walk, swim, platform=platform)
    seen = []

    def receiver(signal=None, sender=None, value=None):
        seen.append(value)

    protofunctions.getField(definition, 'movementMode').watch(definition, receiver)
    platform.submerged = True
    manager.update(0.016, InputState())
    assert swim in seen


# -- selecting -----------------------------------------------------------------

def test_selecting_by_name_makes_that_mode_current():
    walk, fly = modes.WalkMode(name='walk'), modes.FlyMode(name='fly')
    manager, definition = _manager(walk, fly)
    manager.select('fly')
    assert definition.movementMode is fly


def test_selecting_a_name_that_is_not_declared_changes_nothing():
    walk = modes.WalkMode(name='walk')
    manager, definition = _manager(walk)
    manager.select('walk')
    assert not manager.select('nonsense')
    assert definition.movementMode is walk


def test_a_disabled_mode_cannot_be_selected():
    walk = modes.WalkMode(name='walk')
    fly = modes.FlyMode(name='fly', enabled=False)
    manager, definition = _manager(walk, fly)
    manager.select('walk')
    assert not manager.select('fly')
    assert definition.movementMode is walk


def test_the_first_enabled_mode_is_current_to_begin_with():
    walk, fly = modes.WalkMode(name='walk'), modes.FlyMode(name='fly')
    manager, definition = _manager(walk, fly)
    assert definition.movementMode is walk


def test_cycling_steps_through_the_user_selectable_modes():
    """What a "toggle navigation" key does."""
    walk, fly = modes.WalkMode(name='walk'), modes.FlyMode(name='fly')
    manager, definition = _manager(walk, fly)
    manager.cycle()
    assert definition.movementMode is fly
    manager.cycle()
    assert definition.movementMode is walk


def test_cycling_skips_world_imposed_modes():
    """Swimming is not something to cycle into; the water decides."""
    walk = modes.WalkMode(name='walk')
    swim = modes.SwimMode(name='swim')
    fly = modes.FlyMode(name='fly')
    manager, definition = _manager(walk, swim, fly)
    manager.cycle()
    assert definition.movementMode is fly


# -- the world imposing a mode -------------------------------------------------

def test_entering_water_switches_to_swimming_without_being_asked():
    walk, swim = modes.WalkMode(name='walk'), modes.SwimMode(name='swim')
    platform = _Platform()
    manager, definition = _manager(walk, swim, platform=platform)
    manager.update(0.016, InputState())
    assert definition.movementMode is walk
    platform.submerged = True
    manager.update(0.016, InputState())
    assert definition.movementMode is swim


def test_leaving_the_water_restores_the_mode_the_user_had_chosen():
    walk, fly = modes.WalkMode(name='walk'), modes.FlyMode(name='fly')
    swim = modes.SwimMode(name='swim')
    platform = _Platform()
    manager, definition = _manager(walk, swim, fly, platform=platform)
    manager.select('fly')
    platform.submerged = True
    manager.update(0.016, InputState())
    assert definition.movementMode is swim
    platform.submerged = False
    manager.update(0.016, InputState())
    assert definition.movementMode is fly       # not walk: what the user picked


def test_an_imposed_mode_wins_over_an_explicit_selection():
    walk, swim = modes.WalkMode(name='walk'), modes.SwimMode(name='swim')
    platform = _Platform()
    platform.submerged = True
    manager, definition = _manager(walk, swim, platform=platform)
    manager.update(0.016, InputState())
    manager.select('walk')
    manager.update(0.016, InputState())
    assert definition.movementMode is swim


# -- driving the current mode --------------------------------------------------

def test_the_current_mode_gets_the_frame():
    walk = modes.WalkMode(name='walk')
    platform = _Platform()
    manager, _definition = _manager(walk, platform=platform)

    class _E:
        name, state = 'w', 1

        def getModifiers(self):
            return (0, 0, 0)

    inputs = InputState()
    inputs.process(_E())
    manager.update(0.016, inputs)
    assert platform.moved and platform.moved[-1][0] == 'walk'


def test_a_manager_with_no_modes_does_nothing_and_does_not_raise():
    manager, definition = _manager()
    assert manager.update(0.016, InputState()) is None
    assert not definition.movementMode


def test_every_declared_binding_is_reachable_for_a_settings_window():
    """The whole point of declaring: something can enumerate and rewrite them."""
    walk, fly = modes.WalkMode(name='walk'), modes.FlyMode(name='fly')
    manager, _definition = _manager(walk, fly)
    listing = manager.binding_table()
    assert ('walk', 'forward') in [(m, b.command) for m, b in listing]
    assert all(b.label for _m, b in listing)


def test_rebinding_a_command_takes_effect_immediately():
    walk = modes.WalkMode(name='walk')
    platform = _Platform()
    manager, _definition = _manager(walk, platform=platform)
    manager.rebind('walk', 'forward', ['i'])

    class _E:
        name, state = 'i', 1

        def getModifiers(self):
            return (0, 0, 0)

    inputs = InputState()
    inputs.process(_E())
    manager.update(0.016, inputs)
    assert platform.moved[-1][1] == pytest.approx(1.0)


def test_rebinding_an_unknown_command_reports_failure():
    walk = modes.WalkMode(name='walk')
    manager, _definition = _manager(walk)
    assert not manager.rebind('walk', 'nonsense', ['i'])
    assert not manager.rebind('nonsense', 'forward', ['i'])


class TestRetargetingKeepsTheChosenMode:
    """A world that swaps in a character controller must not reset the player.

    ``getNavigation`` rebuilds when what it drives changes -- a controller
    usually comes into being when a world finishes loading, after the context
    has already been navigating the camera.  Rebuilding from scratch would put
    the player back in whichever mode happens to be declared first.
    """

    def _manager(self):
        definition = ContextDefinition()
        definition.movementModes = [modes.WalkMode(name='walk'),
                                    modes.FlyMode(name='fly')]
        return NavigationManager(definition, _Platform()), definition

    def test_retargeting_keeps_the_selected_mode(self):
        manager, definition = self._manager()
        assert manager.select('fly')
        manager.retarget(_Platform())
        assert definition.movementMode.name == 'fly'

    def test_retargeting_drives_the_new_platform(self):
        manager, _definition = self._manager()
        fresh = _Platform()
        manager.retarget(fresh)
        assert manager.platform is fresh

    def test_a_context_reuses_the_manager_when_only_the_platform_moves(self):
        from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin

        class Ctx(ViewPlatformMixin):
            def __init__(self, definition, platform):
                self.contextDefinition = definition
                self._platform = platform

            def getNavigationPlatform(self):
                return self._platform

        definition = ContextDefinition()
        definition.movementModes = [modes.WalkMode(name='walk'),
                                    modes.FlyMode(name='fly')]
        context = Ctx(definition, _Platform())
        first = context.getNavigation()
        first.select('fly')
        context._platform = _Platform()
        second = context.getNavigation()
        assert second is first, "the manager was rebuilt from scratch"
        assert definition.movementMode.name == 'fly'


class TestSelectableIsDecidedOnce:
    def test_a_world_imposed_mode_is_never_offered_to_the_player(self):
        definition = ContextDefinition()
        definition.movementModes = [modes.WalkMode(name='walk'),
                                    modes.SwimMode(name='swim')]
        manager = NavigationManager(definition, _Platform())
        assert [mode.name for mode in manager._selectable()] == ['walk']

    def test_deciding_does_not_ask_the_platform(self):
        """``enter_when`` is a call into the world; it cannot decide this."""
        definition = ContextDefinition()
        definition.movementModes = [modes.SwimMode(name='swim')]
        platform = _Platform()
        platform.asked = 0

        class Counting(modes.SwimMode):
            PROTO = 'UITestCountingSwim'

            def enter_when(self, platform):
                platform.asked += 1
                return super().enter_when(platform)

        definition.movementModes = [Counting(name='swim')]
        manager = NavigationManager(definition, platform)
        platform.asked = 0
        manager._selectable()
        assert platform.asked == 0
