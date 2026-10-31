"""A character its owner steps in small pieces and animates once a frame, and slides that steer and go on."""
import pytest

from OpenGLContext.character.locomotion import ClipMap, ClipSpec, Locomotion, LocomotionInput
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.physics import CharacterState

from ._locomotion_assets import marching, striding, walker_glb, waving


LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))
CLIPS = dict(idle='idle', walk=('walk', 3.0), run=('run', 6.0))
TICK = 1 / 120


def walker():
    from OpenGLContext.character import CharacterModel

    return CharacterModel.load(walker_glb({
        'idle': marching(2.0), 'walk': striding(1.0), 'run': striding(0.5),
        'wave': waving(1.0)}))


@pytest.fixture
def physics():
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=120.0))
    service.add_static(surfaces.shape(surfaces.block((400, 1, 400)), LOOK, translation=(0, -0.5, 0)),
                       proxy='box')
    yield service
    service.close()


@pytest.fixture
def me(physics):
    found = physics.add_character(model=walker(), animations=ClipMap(**CLIPS), position=(0, 0.05, 0))
    found.framed = False
    physics.step(0.0)
    return found


def test_stepping_moves_the_character_and_shows_it_but_does_not_animate_it(me):
    me.set_move((1, 0, 0), 'walk')
    for _ in range(12):
        me.step(TICK)
    assert me.settled is None
    assert me.position[0] > 0.1
    assert tuple(me.node.translation) == pytest.approx(tuple(me.position))
    me.animate(12 * TICK)
    assert me.settled is not None


def test_animating_hears_the_speed_of_the_whole_frame_and_not_of_its_last_step(me):
    me.set_move((1, 0, 0), 'run')
    for _ in range(60):
        me.step(TICK)
    seen = []
    original = me.locomotion.update
    me.locomotion.update = lambda state, dt: (seen.append((state, dt)), original(state, dt))[1]
    me.animate(TICK)
    seen.clear()
    start = float(me.position[0])
    for _ in range(3):
        me.step(TICK)
    me.set_move((0, 0, 0), 'run')
    me.step(TICK)
    me.animate(4 * TICK)
    (state, dt), = seen
    assert dt == pytest.approx(4 * TICK)
    assert state.speed == pytest.approx((float(me.position[0]) - start) / (4 * TICK), rel=1e-6)
    assert 0.0 < state.speed < 6.0


def test_a_landing_in_the_middle_of_a_frame_is_still_there_when_the_frame_animates(me):
    me.jump()
    seen = []
    original = me.locomotion.update
    me.locomotion.update = lambda state, dt: (seen.append(state), original(state, dt))[1]
    landed = []
    keep = landed.append
    me.addEventHandler('landed', function=keep)
    for _ in range(200):
        me.step(TICK)
        if landed:
            break
    assert landed
    for _ in range(3):
        me.step(TICK)
    me.animate(0.05)
    assert seen[-1].landing_speed == pytest.approx(landed[0].speed)
    me.step(TICK)
    me.animate(TICK)
    assert seen[-1].landing_speed is None


def test_update_is_a_step_and_an_animation(me):
    me.set_move((1, 0, 0), 'walk')
    me.update(1 / 60)
    assert me.settled is not None
    assert me.position[0] > 0.0


def test_footsteps_come_with_the_animation_of_the_frame(me):
    heard = []
    keep = heard.append
    me.addEventHandler('footstep', function=keep)
    me.set_move((1, 0, 0), 'walk')
    for _ in range(240):
        me.step(TICK)
    assert heard == []
    for _ in range(120):
        for _ in range(2):
            me.step(TICK)
        me.animate(2 * TICK)
    assert len(heard) >= 2


def test_slide_can_be_steered_and_gone_on_with_and_ended(me):
    me.set_move((1, 0, 0), 'run')
    for _ in range(60):
        me.step(TICK)
    assert me.slide(0.8, 0.3, steer=True)
    me.set_move((0, 0, 1), 'run')
    for _ in range(36):
        me.step(TICK)
    assert me.state == CharacterState.SLIDING
    assert me.velocity[2] == pytest.approx(6.0, abs=0.1)
    assert me.extend_slide(0.8)
    me.step(TICK)
    assert me._controller.height == pytest.approx(me.capabilities.crouchHeight, abs=1e-9)
    assert me.end_slide()
    assert me.state == CharacterState.STANDING
    assert not me.end_slide()
    assert not me.extend_slide(0.8)


def test_a_slide_that_is_not_steered_ignores_the_input_as_before(me):
    me.set_move((1, 0, 0), 'run')
    for _ in range(60):
        me.step(TICK)
    me.slide(0.8, 0.3)
    me.set_move((-1, 0, 0), 'run')
    before = float(me.position[0])
    for _ in range(36):
        me.step(TICK)
    assert float(me.position[0]) > before


def test_a_clip_may_say_how_fast_its_action_plays():
    model = walker()
    clips = ClipMap(idle='idle', walk=('walk', 3.0), run=('run', 6.0),
                    jump_up=ClipSpec('wave', rate=2.5))
    locomotion = Locomotion(clips, model)
    locomotion.update(LocomotionInput(grounded=False, state='airborne', vertical_speed=3.0), 0.05)
    assert model.layer('action').current.speed == pytest.approx(2.5)


def test_an_action_with_no_rate_plays_as_authored():
    model = walker()
    clips = ClipMap(idle='idle', walk=('walk', 3.0), run=('run', 6.0), jump_up='wave')
    locomotion = Locomotion(clips, model)
    locomotion.update(LocomotionInput(grounded=False, state='airborne', vertical_speed=3.0), 0.05)
    assert model.layer('action').current.speed == pytest.approx(1.0)


@pytest.mark.parametrize('steps', [True, False])
def test_a_window_that_steps_its_physics_itself_has_no_step_made_for_it(gl_context, steps):
    from OpenGLContext.testing.scenes import scene_context

    floor = surfaces.shape(surfaces.block((20, 1, 20)), LOOK, translation=(0, -0.5, 0))
    with scene_context([floor], size=(48, 48)) as context:
        context.stepsPhysics = steps
        service = context.physics
        frames: list[float] = []
        original = service.frame
        service.frame = lambda dt: (frames.append(dt), original(dt))[1]
        for _ in range(3):
            context.runFrameHooks()
        assert bool(frames) is steps


# -- bodies a character walks through ---------------------------------------------------------

def wall_across(physics, **options):
    return physics.add_static(None, proxy=Proxy.box((6.0, 3.0, 0.4)),
                              translation=(0.0, 1.5, -4.0), **options)


def walk_into(me, seconds=2.5):
    me.set_move((0, 0, -1), 'walk')
    for _ in range(round(seconds / TICK)):
        me.step(TICK)
    return float(me.position[2])


def test_a_wall_stops_a_character_that_walks_into_it(physics):
    wall_across(physics)
    me = physics.add_character(position=(0, 0.05, 0))
    me.framed = False
    assert walk_into(me) > -4.0


def test_a_wall_that_does_not_block_characters_is_walked_through_and_still_met_by_a_ray(physics):
    wall = wall_across(physics, blocks_characters=False)
    me = physics.add_character(position=(0, 0.05, 0))
    me.framed = False
    assert physics.raycast((0, 1.0, -1.0), (0, 0, -1), 10.0).body is wall
    assert walk_into(me) < -4.5


def test_a_character_made_after_the_wall_walks_through_it_too(physics):
    wall_across(physics, blocks_characters=False)
    first = physics.add_character(position=(0, 0.05, 0))
    first.framed = False
    second = physics.add_character(position=(1, 0.05, 0))
    second.framed = False
    assert walk_into(first) < -4.5
    assert walk_into(second) < -4.5


def test_a_wall_taken_away_leaves_its_place_to_the_next_body(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    me.framed = False
    wall = wall_across(physics, blocks_characters=False)
    physics.remove(wall)
    physics.step(TICK)
    solid = wall_across(physics)
    physics.step(TICK)
    assert solid.alive
    assert walk_into(me) > -4.0


# -- characters that walk through one another -------------------------------------------------

def corridor(physics, width=1.0):
    """Walls along x either side of a corridor ``width`` metres wide, one capsule across."""
    for side in (-1, 1):
        physics.add_static(None, proxy=Proxy.box((40.0, 3.0, 0.4)),
                           translation=(0.0, 1.5, side * (width / 2 + 0.2)))


def towards_each_other(physics, seconds=6.0, **options):
    """Two characters in the corridor walking at each other; their x when the time is up."""
    west = physics.add_character(position=(-3, 0.05, 0.01), **options)
    east = physics.add_character(position=(3, 0.05, -0.01), **options)
    for each, heading in ((west, 1.0), (east, -1.0)):
        each.framed = False
        each.set_move((heading, 0, 0), 'walk')
    for _ in range(round(seconds / TICK)):
        west.step(TICK)
        east.step(TICK)
    return float(west.position[0]), float(east.position[0])


def test_two_characters_meeting_in_a_corridor_one_wide_block_each_other(physics):
    corridor(physics)
    west, east = towards_each_other(physics)
    assert west < east


def test_characters_of_one_pass_group_walk_through_each_other(physics):
    corridor(physics)
    west, east = towards_each_other(physics, pass_group='bots')
    assert west > 2.0 and east < -2.0


def test_a_character_outside_the_pass_group_still_blocks_it(physics):
    corridor(physics)
    me = physics.add_character(position=(0, 0.05, 0))
    bot = physics.add_character(position=(-3, 0.05, 0), pass_group='bots')
    other = physics.add_character(position=(3, 0.05, 0), pass_group='bots')
    assert (me.pass_group, bot.pass_group) == (None, 'bots')
    for each in (me, bot, other):
        each.framed = False
    bot.set_move((1, 0, 0), 'walk')
    for _ in range(round(3.0 / TICK)):
        bot.step(TICK)
    # Characters push one another by their masses: the bot shoves the
    # character outside its group along rather than passing through it.
    assert float(me.position[0]) > 0.5
    assert float(me.position[0]) - float(bot.position[0]) >= 2 * me.radius - 0.02
    assert physics.raycast((-6, 1.0, 0), (1, 0, 0), 20.0).body is bot.body


def test_a_pass_group_can_be_joined_and_left(physics):
    corridor(physics)
    west = physics.add_character(position=(-3, 0.05, 0.01))
    east = physics.add_character(position=(3, 0.05, -0.01), pass_group='bots')
    west.pass_group = 'bots'
    assert west.pass_group == 'bots'
    west.pass_group = None
    for each, heading in ((west, 1.0), (east, -1.0)):
        each.framed = False
        each.set_move((heading, 0, 0), 'walk')
    for _ in range(round(6.0 / TICK)):
        west.step(TICK)
        east.step(TICK)
    assert float(west.position[0]) < float(east.position[0])


def test_a_removed_member_leaves_its_slot_to_the_next_body(physics):
    corridor(physics)
    me = physics.add_character(position=(-3, 0.05, 0), pass_group='bots')
    gone = physics.add_character(position=(3, 0.05, 0), pass_group='bots')
    me.framed = False
    gone.remove()
    physics.step(TICK)
    physics.add_static(None, proxy=Proxy.box((0.4, 3.0, 2.0)), translation=(0.0, 1.5, 0.0))
    physics.step(TICK)
    me.set_move((1, 0, 0), 'walk')
    for _ in range(round(3.0 / TICK)):
        me.step(TICK)
    assert float(me.position[0]) < 0.0
