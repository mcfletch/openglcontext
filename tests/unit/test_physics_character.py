"""Characters in a physics service: walkers stepped by the frame, seen by the world as kinematic bodies.

A character is stepped on the render thread, against a copy of the bodies, so
input reaches it with no tick between. The world sees a stand-in that carries the
character's velocity, which is how it pushes a crate and how a crate pushes it.
"""
import time

import numpy as np
import pytest
from omi_physics.character import CharacterCapabilities, CharacterState

from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def block(size, at=(0, 0, 0)):
    return surfaces.shape(surfaces.block(size), LOOK, translation=at)


def make(mode='inline') -> Physics:
    service = Physics(PhysicsDefinition(mode=mode, maxCatchUp=2.0, tickHz=120.0))
    service.add_static(block((60, 1, 60), at=(0, -0.5, 0)), proxy='box')
    return service


def run_for(physics, seconds, frame=1 / 60, setup=None):
    for _ in range(int(round(seconds / frame))):
        if setup is not None:
            setup()
        physics.frame(frame)
        if physics.definition.mode == 'thread':
            time.sleep(frame)


@pytest.fixture(params=['inline', 'thread'])
def world(request):
    service = make(request.param)
    yield service
    service.close()


@pytest.fixture
def inline():
    service = make('inline')
    yield service
    service.close()


def test_a_character_dropped_above_the_floor_lands_and_stands_on_it(world):
    me = world.add_character(position=(0, 2, 0))
    run_for(world, 1.5)
    assert me.grounded
    assert me.position[1] == pytest.approx(0.0, abs=0.03)          # the feet are on the floor
    assert me.state == CharacterState.STANDING
    assert me.eye[1] == pytest.approx(1.6, abs=0.05)


def test_the_character_walks_at_the_speed_of_its_mode(world):
    me = world.add_character(position=(0, 0.05, 0))
    run_for(world, 0.5)
    start = me.position.copy()
    run_for(world, 1.0, setup=lambda: me.set_move((1, 0, 0), mode='walk'))
    assert me.position[0] - start[0] == pytest.approx(me.capabilities.walkSpeed, rel=0.15)
    assert me.velocity[0] == pytest.approx(me.capabilities.walkSpeed, rel=0.1)


def test_a_jump_reaches_the_height_the_capabilities_name(world):
    caps = CharacterCapabilities(jumpHeight=1.2)
    me = world.add_character(capabilities=caps, position=(0, 0.05, 0))
    run_for(world, 0.5)
    base = me.position[1]
    assert me.jump() is True
    top = 0.0
    for _ in range(90):
        world.frame(1 / 60)
        if world.definition.mode == 'thread':
            time.sleep(1 / 60)
        top = max(top, me.position[1] - base)
    assert top == pytest.approx(1.2, abs=0.03)


def test_a_wall_stops_the_character(inline):
    inline.add_static(block((1, 4, 10), at=(5, 2, 0)), proxy='box')
    me = inline.add_character(position=(0, 0.05, 0))
    run_for(inline, 4.0, setup=lambda: me.set_move((1, 0, 0), mode='run'))
    assert me.position[0] == pytest.approx(4.5 - me.capabilities.radius, abs=0.1)


def test_the_node_stands_where_the_feet_are(inline):
    node = block((0.2, 1.8, 0.2))
    me = inline.add_character(node=node, position=(1, 0.05, 2))
    run_for(inline, 1.0, setup=lambda: me.set_move((0, 0, 1)))
    assert tuple(node.translation) == pytest.approx(tuple(me.position), abs=1e-6)


def test_landing_is_an_event_with_the_speed_it_landed_at(inline):
    heard = []
    keep = heard.append
    me = inline.add_character(position=(0, 4, 0))
    me.addEventHandler('landed', function=keep)
    run_for(inline, 2.0)
    assert len(heard) == 1
    assert heard[0].speed == pytest.approx(np.sqrt(2 * 9.81 * 4.0), rel=0.1)
    assert heard[0].character is me


def test_slide_and_knock_down_are_the_controllers(inline):
    me = inline.add_character(position=(0, 0.05, 0))
    run_for(inline, 0.5)
    assert me.slide(0.8, rise=0.3) is True
    run_for(inline, 0.2)
    assert me.state == CharacterState.SLIDING
    run_for(inline, 1.0)
    me.knock_down()
    assert me.state == CharacterState.DOWN
    me.get_up()
    run_for(inline, 0.2)
    assert me.state == CharacterState.STANDING


def test_a_walker_pushes_a_light_crate_and_not_a_heavy_one(inline):
    light = inline.add_dynamic(block((0.8, 0.8, 0.8), at=(2, 0.4, 0)), proxy='box', mass=20.0)
    heavy = inline.add_dynamic(block((0.8, 0.8, 0.8), at=(2, 0.4, 5)), proxy='box', mass=2000.0)
    me = inline.add_character(position=(0, 0.05, 0))
    they = inline.add_character(position=(0, 0.05, 5))
    run_for(inline, 2.5, setup=lambda: (me.set_move((1, 0, 0)), they.set_move((1, 0, 0))))
    assert light.position[0] > 3.0
    assert heavy.position[0] == pytest.approx(2.0, abs=0.15)
    assert me.position[0] > 2.0
    assert they.position[0] < 1.4


def test_a_crate_thrown_at_the_character_knocks_it_back(inline):
    me = inline.add_character(position=(0, 0.05, 0))
    run_for(inline, 0.5)
    crate = inline.add_dynamic(block((0.5, 0.5, 0.5), at=(3, 0.9, 0)), proxy='box', mass=40.0)
    crate.set_velocity((-8, 0, 0))
    inline.gravity = (0, 0, 0)
    run_for(inline, 0.6)
    assert me.position[0] < -0.1


def test_a_character_standing_on_a_drifting_crate_is_carried(inline):
    crate = inline.add_dynamic(block((2, 0.4, 2), at=(0, 0.2, 0)), proxy='box', mass=500.0,
                               linear_damping=0.0)
    me = inline.add_character(position=(0, 0.45, 0))
    run_for(inline, 0.5)
    run_for(inline, 1.0, setup=lambda: crate.set_velocity((1.0, 0, 0)))      # a lift, carrying on
    assert me.position[0] > 0.5


def test_a_character_triggers_a_zone_it_walks_into(inline):
    zone = inline.add_trigger(block((2, 2, 2), at=(4, 1, 0)), proxy='box')
    heard = []
    keep = heard.append
    zone.addEventHandler('enter', function=keep)
    me = inline.add_character(position=(0, 0.05, 0))
    run_for(inline, 3.0, setup=lambda: me.set_move((1, 0, 0)))
    assert [hit.other for hit in heard] == [me.body]


def test_two_characters_do_not_walk_through_each_other(inline):
    first = inline.add_character(position=(0, 0.05, 0))
    second = inline.add_character(position=(2, 0.05, 0))
    run_for(inline, 2.5, setup=lambda: first.set_move((1, 0, 0)))
    assert first.position[0] < second.position[0]


def test_remove_takes_the_stand_in_out_of_the_world(inline):
    me = inline.add_character(position=(0, 0.05, 0))
    body = me.body
    me.remove()
    me.remove()
    assert not body.alive and not me.alive
    run_for(inline, 0.2)


def test_teleport_puts_the_character_somewhere_safe(inline):
    me = inline.add_character(position=(0, 0.05, 0))
    me.teleport((10, 3, 10))
    run_for(inline, 1.0)
    assert me.position[0] == pytest.approx(10, abs=0.01)
    assert me.position[1] == pytest.approx(0.0, abs=0.05)


def test_a_character_hit_on_the_stand_in_is_a_body_event(inline):
    me = inline.add_character(position=(0, 0.05, 0))
    heard = []
    keep = heard.append
    me.addEventHandler('hit', function=keep)
    run_for(inline, 0.3)
    crate = inline.add_dynamic(block((0.5, 0.5, 0.5), at=(2, 0.3, 0)), proxy='box', mass=10.0)
    crate.set_velocity((-6, 0, 0))
    run_for(inline, 0.6)
    assert heard and heard[0].other is crate


# -- running along a course ------------------------------------------------------

def straight_course(length=200.0):
    from OpenGLContext.scenegraph.roadcourse import RoadCourse
    return RoadCourse(np.array([(0.0, 0.0, 0.0), (0.0, 0.0, -length / 2), (0.0, 0.0, -length)]))


def test_a_character_runs_along_a_course_at_the_speed_asked(inline):
    me = inline.add_character(position=(0, 0.05, 0))
    run_for(inline, 0.5)
    me.run_along(straight_course(), speed=8.0)
    run_for(inline, 2.0)
    assert me.position[2] == pytest.approx(-16.0, abs=2.0)
    assert me.position[0] == pytest.approx(0.0, abs=0.1)


def test_hop_to_moves_the_character_across_to_a_lane(inline):
    me = inline.add_character(position=(0, 0.05, 0))
    me.run_along(straight_course(), speed=6.0)
    run_for(inline, 1.0)
    me.hop_to(2.0, over=0.2)
    run_for(inline, 1.0)
    assert abs(me.position[0]) == pytest.approx(2.0, abs=0.15)


def test_stop_running_along_gives_the_moves_back_to_the_caller(inline):
    me = inline.add_character(position=(0, 0.05, 0))
    me.run_along(straight_course(), speed=6.0)
    run_for(inline, 0.5)
    me.stop_running_along()
    me.set_move((0, 0, 0))
    run_for(inline, 1.0)
    assert me.velocity[2] == pytest.approx(0.0, abs=0.05)


def test_hop_to_without_a_course_is_refused(inline):
    me = inline.add_character(position=(0, 0.05, 0))
    with pytest.raises(RuntimeError, match='run_along'):
        me.hop_to(1.0)
