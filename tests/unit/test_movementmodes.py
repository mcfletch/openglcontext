"""Movement modes as scenegraph nodes: declared, parameterised, watchable."""

import pytest
from vrml import node

from OpenGLContext.events.inputstate import InputState
from OpenGLContext.move import modes


class _Platform:
    """The little of a view platform a mode drives."""

    def __init__(self):
        self.moved = []
        self.jumped = 0
        self.yaw = 0.0
        self.pitch = 0.0
        self.submerged = False

    def set_move(self, forward=0.0, strafe=0.0, mode='walk'):
        self.moved.append((forward, strafe, mode))

    def set_fly_move(self, forward=0.0, strafe=0.0, up=0.0):
        self.moved.append((forward, strafe, up))

    def jump(self):
        self.jumped += 1

    def turn(self, delta):
        self.yaw += delta

    def look(self, delta):
        self.pitch += delta


def press(state, *names):
    class _E:
        def __init__(self, name):
            self.name, self.state = name, 1

        def getModifiers(self):
            return (0, 0, 0)
    for name in names:
        state.process(_E(name))
    return state


# -- the base prototype -------------------------------------------------------

def test_a_mode_is_a_scenegraph_node():
    """So it can be declared in a parsed file and carried in an SFNode field."""
    assert issubclass(modes.MovementMode, node.Node)
    assert modes.WalkMode.PROTO == 'WalkMode'
    assert isinstance(modes.WalkMode(), node.Node)


def test_a_mode_carries_a_name_and_can_be_disabled():
    walk = modes.WalkMode(name='walk')
    assert walk.name == 'walk'
    assert walk.enabled
    walk.enabled = False
    assert not walk.enabled


def test_each_mode_declares_its_own_typed_parameters():
    """Not a free-form mapping: the field system validates and defaults them,
    so a game setting a swim speed of 10 needs no new validation layer."""
    swim = modes.SwimMode(swimSpeed=10.0)
    assert swim.swimSpeed == pytest.approx(10.0)
    assert modes.SwimMode().swimSpeed != 10.0        # a real default exists
    walk = modes.WalkMode(walkSpeed=3.0, runSpeed=6.0)
    assert (walk.walkSpeed, walk.runSpeed) == pytest.approx((3.0, 6.0))


def test_a_parameter_of_the_wrong_type_is_rejected_by_the_field():
    with pytest.raises(ValueError):
        modes.SwimMode(swimSpeed='not a number')


def test_parameters_are_per_instance_so_two_games_can_differ():
    assert modes.SwimMode(swimSpeed=3.0).swimSpeed != \
        modes.SwimMode(swimSpeed=10.0).swimSpeed


# -- bindings -----------------------------------------------------------------

def test_a_binding_is_a_node_so_a_settings_window_can_edit_it():
    binding = modes.KeyBinding(command='forward', label='Forward', keys=['w', '<up>'])
    assert isinstance(binding, node.Node)
    assert binding.command == 'forward'
    assert list(binding.keys) == ['w', '<up>']


def test_a_mode_ships_default_bindings():
    assert modes.WalkMode().bindings
    assert all(isinstance(b, modes.KeyBinding) for b in modes.WalkMode().bindings)


def test_bindings_can_be_replaced_wholesale():
    """What a rebinding window does: hand the mode a new set."""
    walk = modes.WalkMode()
    walk.bindings = [modes.KeyBinding(command='forward', keys=['i'])]
    assert walk.keys_for('forward') == ('i',)


def test_an_unbound_command_resolves_to_no_keys():
    assert modes.WalkMode().keys_for('nonsense') == ()


def test_the_default_bindings_name_every_command_the_mode_uses():
    """A command with no binding is unreachable, and a binding for a command
    the mode does not implement is dead weight in the settings window."""
    for factory in (modes.WalkMode, modes.FlyMode, modes.SwimMode, modes.FPSMode):
        mode = factory()
        bound = {b.command for b in mode.bindings}
        assert bound == set(mode.commands), factory.__name__


def test_every_binding_carries_a_label_for_the_settings_window():
    for factory in (modes.WalkMode, modes.FlyMode, modes.SwimMode, modes.FPSMode):
        for binding in factory().bindings:
            assert binding.label, (factory.__name__, binding.command)


# -- what a mode does with sampled input --------------------------------------

def test_walking_forward_and_jumping_happen_in_the_same_frame():
    """The defect this whole structure exists to remove."""
    walk, platform = modes.WalkMode(), _Platform()
    state = press(InputState(), 'w', ' ')
    walk.update(0.016, state, platform)
    assert platform.moved and platform.moved[0][0] == pytest.approx(1.0)
    assert platform.jumped == 1


def test_a_held_jump_key_fires_once_not_every_frame():
    walk, platform = modes.WalkMode(), _Platform()
    state = press(InputState(), ' ')
    for _ in range(5):
        walk.update(0.016, state, platform)
    assert platform.jumped == 1


def test_walking_uses_the_run_tier_when_the_run_key_is_held():
    walk, platform = modes.WalkMode(), _Platform()
    walk.update(0.016, press(InputState(), 'w'), platform)
    assert platform.moved[-1][2] == 'walk'
    walk.update(0.016, press(InputState(), 'w', '<shift>'), platform)
    assert platform.moved[-1][2] == 'run'


def test_turning_left_and_right_are_opposite():
    walk, platform = modes.WalkMode(), _Platform()
    walk.update(0.1, press(InputState(), 'q'), platform)
    left = platform.yaw
    platform.yaw = 0.0
    walk.update(0.1, press(InputState(), 'e'), platform)
    assert left == pytest.approx(-platform.yaw)
    assert left != 0.0


def test_flying_adds_a_vertical_axis_that_walking_has_not():
    fly, platform = modes.FlyMode(), _Platform()
    fly.update(0.016, press(InputState(), 'w', 'c'), platform)
    assert platform.moved[-1][2] != 0.0          # `up` component is driven


def test_swimming_moves_at_its_own_speed_setting():
    swim, platform = modes.SwimMode(swimSpeed=7.0), _Platform()
    swim.update(0.016, press(InputState(), 'w'), platform)
    assert platform.moved


def test_mouse_look_turns_and_pitches_from_relative_motion():
    fps, platform = modes.FPSMode(), _Platform()
    state = InputState()
    state.mouse_moved(20, 10)
    fps.update(0.016, state, platform)
    assert platform.yaw != 0.0
    assert platform.pitch != 0.0


def test_mouse_look_sensitivity_scales_the_turn():
    slow, fast = modes.FPSMode(sensitivity=0.001), modes.FPSMode(sensitivity=0.01)
    a, b = _Platform(), _Platform()
    for mode, platform in ((slow, a), (fast, b)):
        state = InputState()
        state.mouse_moved(20, 0)
        mode.update(0.016, state, platform)
    assert abs(b.yaw) > abs(a.yaw)


def test_inverting_the_look_axis_flips_the_pitch():
    normal, inverted = modes.FPSMode(), modes.FPSMode(invertLook=True)
    a, b = _Platform(), _Platform()
    for mode, platform in ((normal, a), (inverted, b)):
        state = InputState()
        state.mouse_moved(0, 10)
        mode.update(0.016, state, platform)
    assert a.pitch == pytest.approx(-b.pitch)


# -- world-imposed modes ------------------------------------------------------

def test_a_user_selected_mode_never_claims_the_avatar():
    """Walk and fly are chosen; they do not impose themselves."""
    platform = _Platform()
    assert not modes.WalkMode().enter_when(platform)
    assert not modes.FlyMode().enter_when(platform)


def test_swimming_claims_the_avatar_when_it_is_submerged():
    """The world decides this one, which is why the test is on the mode."""
    swim, platform = modes.SwimMode(), _Platform()
    assert not swim.enter_when(platform)
    platform.submerged = True
    assert swim.enter_when(platform)


def test_a_disabled_mode_never_claims_the_avatar():
    swim, platform = modes.SwimMode(enabled=False), _Platform()
    platform.submerged = True
    assert not swim.enter_when(platform)


# -- bindings that want a modifier held ---------------------------------------

class _Inputs:
    """A hand-built input state: what is held, and with which modifiers."""

    def __init__(self, held=(), modifiers=None):
        self._held = set(held)
        self._modifiers = dict(modifiers or {})

    def held(self, *names):
        return any(name in self._held for name in names)

    def pressed(self, *names):
        return False

    def axis(self, positive, negative):
        return ((1.0 if self.held(*positive) else 0.0)
                - (1.0 if self.held(*negative) else 0.0))

    def modifiers(self, name):
        return self._modifiers.get(name, (0, 0, 0))

    def mouse_delta(self):
        return (0.0, 0.0)


def _walk():
    return modes.WalkMode(name='walk')


def test_a_binding_asks_for_no_modifier_by_default():
    binding = modes.KeyBinding(command='forward', keys=['w'])
    assert binding.modifier == ''


def test_a_command_bound_with_a_modifier_needs_it_held():
    """`ctrl` + an arrow tilts the view; the same arrow alone walks, so the two
    can only be told apart by the modifier."""
    mode = _walk()
    mode.bindings = list(mode.bindings) + [
        modes.KeyBinding(command='lookup', keys=['<up>'], modifier='ctrl')]
    assert not mode.active(_Inputs(['<up>']), 'lookup')
    assert mode.active(_Inputs(['<up>'], {'<up>': (0, 1, 0)}), 'lookup')


def test_a_plain_binding_loses_its_key_while_the_modified_one_claims_it():
    """Holding ctrl and pushing up should tilt without also walking forward."""
    mode = _walk()
    mode.bindings = list(mode.bindings) + [
        modes.KeyBinding(command='lookup', keys=['<up>'], modifier='ctrl')]
    inputs = _Inputs(['<up>'], {'<up>': (0, 1, 0)})
    assert not mode.active(inputs, 'forward')
    assert mode.active(_Inputs(['<up>']), 'forward')


def test_a_modifier_no_other_binding_claims_does_not_disable_the_key():
    """Shift is bound to run, so shift + w has to keep walking."""
    mode = _walk()
    inputs = _Inputs(['w', '<shift>'], {'w': (1, 0, 0)})
    assert mode.active(inputs, 'forward')


def test_the_axis_helper_honours_the_modifier_rule():
    mode = _walk()
    mode.bindings = list(mode.bindings) + [
        modes.KeyBinding(command='lookup', keys=['<up>'], modifier='ctrl')]
    inputs = _Inputs(['<up>'], {'<up>': (0, 1, 0)})
    assert mode._axis(inputs, 'forward', 'back') == 0.0


@pytest.mark.parametrize('name,index', [('shift', 0), ('ctrl', 1), ('alt', 2)])
def test_each_modifier_name_reads_its_own_flag(name, index):
    mode = _walk()
    mode.bindings = [modes.KeyBinding(command='forward', keys=['x'],
                                      modifier=name)]
    flags = [0, 0, 0]
    flags[index] = 1
    assert mode.active(_Inputs(['x'], {'x': tuple(flags)}), 'forward')
    assert not mode.active(_Inputs(['x'], {'x': (0, 0, 0)}), 'forward')


def test_an_unknown_modifier_name_never_matches():
    """Better a binding that does nothing than one that fires on any key."""
    mode = _walk()
    mode.bindings = [modes.KeyBinding(command='forward', keys=['x'],
                                      modifier='meta')]
    assert not mode.active(_Inputs(['x'], {'x': (1, 1, 1)}), 'forward')


def test_a_ground_mode_can_tilt_the_view_with_the_modified_arrows():
    """Looking up and down is part of walking around a world, and a mode that
    cannot do it needs a second input system bolted alongside."""
    mode = _walk()
    assert 'lookup' in mode.commands and 'lookdown' in mode.commands
    assert mode.keys_for('lookup') == ('<up>',)


class _Recorder:
    submerged = False

    def __init__(self):
        self.looked = 0.0

    def set_move(self, forward=0.0, strafe=0.0, mode='walk'):
        self.forward = forward

    def turn(self, delta):
        pass

    def look(self, delta):
        self.looked += delta

    def jump(self):
        pass


def test_holding_the_look_binding_tilts_and_does_not_walk():
    """A rising platform pitch tips the gaze down, so looking *up* is a
    negative delta -- the same convention the mouse look uses."""
    mode = _walk()
    platform = _Recorder()
    mode.update(0.1, _Inputs(['<up>'], {'<up>': (0, 1, 0)}), platform)
    assert platform.looked < 0
    assert platform.forward == 0.0


# -- turn acceleration --------------------------------------------------------

class _Turner:
    submerged = False

    def __init__(self):
        self.turned = 0.0

    def set_move(self, forward=0.0, strafe=0.0, mode='walk'):
        pass

    def set_fly_move(self, forward=0.0, strafe=0.0, up=0.0):
        pass

    def turn(self, delta):
        self.turned += delta

    def look(self, delta):
        pass

    def jump(self):
        pass


def test_turning_is_steady_by_default():
    mode = modes.WalkMode(name='walk', turnRate=1.0)
    platform = _Turner()
    for _ in range(3):
        mode.update(0.1, _Inputs(['e']), platform)
    assert platform.turned == pytest.approx(0.3)


def test_a_held_turn_can_accelerate():
    """A viewer wants both a precise nudge and a quick spin, and one rate gives
    only one of them."""
    mode = modes.WalkMode(name='walk', turnRate=1.0, turnAcceleration=3.0)
    platform = _Turner()
    inputs = _Inputs(['e'])
    mode.update(0.1, inputs, platform)
    first = platform.turned
    for _ in range(20):
        mode.update(0.1, inputs, platform)
    last = platform.turned
    mode.update(0.1, inputs, platform)
    assert platform.turned - last == pytest.approx(first * 3.0, rel=1e-3)


def test_letting_go_resets_the_ramp():
    """Otherwise the next tap starts at full speed and overshoots."""
    mode = modes.WalkMode(name='walk', turnRate=1.0, turnAcceleration=3.0)
    platform = _Turner()
    for _ in range(20):
        mode.update(0.1, _Inputs(['e']), platform)
    mode.update(0.1, _Inputs([]), platform)          # released
    before = platform.turned
    mode.update(0.1, _Inputs(['e']), platform)
    assert platform.turned - before == pytest.approx(0.1)


def test_changing_direction_resets_the_ramp():
    mode = modes.WalkMode(name='walk', turnRate=1.0, turnAcceleration=3.0)
    platform = _Turner()
    for _ in range(20):
        mode.update(0.1, _Inputs(['e']), platform)
    before = platform.turned
    mode.update(0.1, _Inputs(['q']), platform)
    assert platform.turned - before == pytest.approx(-0.1)
