"""Bodies made from a shape alone, sight lines, trigger overlaps and characters their owner steps.

A level cooked elsewhere, a hit capsule and a trigger volume have no scenegraph
node. They are added with ``None`` for the node and a :class:`Proxy` for the shape.
"""
import numpy as np
import pytest

from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition



@pytest.fixture(params=['inline', 'thread'])
def physics(request):
    service = Physics(PhysicsDefinition(mode=request.param, colliders='none',
                                        maxCatchUp=2.0, tickHz=100.0))
    yield service
    service.close()


@pytest.fixture
def inline():
    service = Physics(PhysicsDefinition(mode='inline', colliders='none', maxCatchUp=2.0))
    yield service
    service.close()


def wall(x=5.0, edge=20.0):
    points = np.array([(x, -edge, -edge), (x, edge, -edge), (x, edge, edge), (x, -edge, edge)],
                      dtype='d')
    return Proxy.trimesh(points, np.array([(0, 1, 2), (0, 2, 3)], dtype='i'))


def floor():
    points = np.array([(-30, 0, -30), (-30, 0, 30), (30, 0, 30), (30, 0, -30)], dtype='d')
    return Proxy.trimesh(points, np.array([(0, 1, 2), (0, 2, 3)], dtype='i'))


def test_a_static_trimesh_without_a_node_is_hit_with_its_triangle(physics):
    level = physics.add_static(None, proxy=wall())
    hit = physics.raycast((0, 0, 0), (1, 0, 0))
    assert hit is not None and hit.body is level
    assert hit.distance == pytest.approx(5.0)
    assert hit.triangle in (0, 1)


def test_a_body_without_a_node_has_none(physics):
    assert physics.add_static(None, proxy=wall()).node is None


def test_a_body_without_a_node_is_placed_by_translation(physics):
    ball = physics.add_kinematic(None, proxy=Proxy.sphere(0.5), translation=(10, 0, 0))
    hit = physics.raycast((0, 0, 0), (1, 0, 0))
    assert hit is not None and hit.body is ball
    assert hit.distance == pytest.approx(9.5)


def test_a_body_without_a_node_moves_with_set_transform(physics):
    ball = physics.add_kinematic(None, proxy=Proxy.sphere(0.5), translation=(10, 0, 0))
    ball.set_transform((0, 0, 7))
    assert physics.raycast((0, 0, 0), (1, 0, 0)) is None
    assert physics.raycast((0, 0, 0), (0, 0, 1)).distance == pytest.approx(6.5)


def test_a_body_without_a_node_can_be_removed(physics):
    ball = physics.add_kinematic(None, proxy=Proxy.sphere(0.5), translation=(10, 0, 0))
    ball.remove()
    assert physics.raycast((0, 0, 0), (1, 0, 0)) is None


def test_a_nodeless_body_needs_a_shape_not_a_strategy(physics):
    with pytest.raises(TypeError, match='shape'):
        physics.add_static(None)
    with pytest.raises(TypeError, match='shape'):
        physics.add_static(None, proxy='box')


def test_two_nodeless_bodies_are_two_bodies(physics):
    first = physics.add_static(None, proxy=wall(5.0))
    second = physics.add_static(None, proxy=wall(9.0))
    assert first is not second
    assert physics.raycast((6, 0, 0), (1, 0, 0)).body is second


# -- line of sight -------------------------------------------------------------

def test_a_clear_line_of_sight_is_true(physics):
    physics.add_static(None, proxy=wall(5.0))
    assert physics.line_of_sight((0, 0, 0), (4, 0, 0)) is True


def test_a_wall_between_two_points_blocks_the_sight(physics):
    physics.add_static(None, proxy=wall(5.0))
    assert physics.line_of_sight((0, 0, 0), (9, 0, 0)) is False


def test_a_wall_beyond_the_far_point_does_not_block(physics):
    physics.add_static(None, proxy=wall(5.0))
    assert physics.line_of_sight((6, 0, 0), (0, 0, 0)) is False
    assert physics.line_of_sight((0, 0, 0), (4.9, 0, 0)) is True


def test_two_points_in_one_place_see_each_other(physics):
    physics.add_static(None, proxy=wall(5.0))
    assert physics.line_of_sight((1, 1, 1), (1, 1, 1)) is True


def test_sight_passes_the_bodies_named_in_skip(physics):
    between = physics.add_kinematic(None, proxy=Proxy.sphere(0.5), translation=(3, 0, 0))
    assert physics.line_of_sight((0, 0, 0), (6, 0, 0)) is False
    assert physics.line_of_sight((0, 0, 0), (6, 0, 0), skip=between) is True
    assert physics.line_of_sight((0, 0, 0), (6, 0, 0), skip=[between]) is True


# -- trigger overlaps ----------------------------------------------------------

def test_overlap_with_triggers_lists_the_volumes_a_shape_is_in(physics):
    pad = physics.add_trigger(None, proxy=Proxy.box((4, 4, 4)), translation=(10, 0, 0))
    other = physics.add_trigger(None, proxy=Proxy.box((4, 4, 4)), translation=(30, 0, 0))
    inside = physics.overlap(Proxy.box((1, 1, 1)), (10.5, 0, 0), triggers=True)
    assert inside == [pad]
    assert other not in inside


def test_overlap_with_triggers_is_empty_outside_them(physics):
    physics.add_trigger(None, proxy=Proxy.box((4, 4, 4)), translation=(10, 0, 0))
    assert physics.overlap(Proxy.box((1, 1, 1)), (20, 0, 0), triggers=True) == []


def test_overlap_without_triggers_does_not_list_them(physics):
    physics.add_trigger(None, proxy=Proxy.box((4, 4, 4)), translation=(10, 0, 0))
    assert physics.overlap(Proxy.box((1, 1, 1)), (10, 0, 0)) == []


def test_overlap_with_triggers_does_not_list_solid_bodies(physics):
    physics.add_static(None, proxy=Proxy.box((4, 4, 4)), translation=(10, 0, 0))
    assert physics.overlap(Proxy.box((1, 1, 1)), (10, 0, 0), triggers=True) == []


def test_a_removed_trigger_is_not_listed(physics):
    pad = physics.add_trigger(None, proxy=Proxy.box((4, 4, 4)), translation=(10, 0, 0))
    pad.remove()
    assert physics.overlap(Proxy.box((1, 1, 1)), (10, 0, 0), triggers=True) == []


# -- characters the owner steps ------------------------------------------------

def test_the_service_lists_its_characters(inline):
    inline.add_static(None, proxy=floor())
    me = inline.add_character(position=(0, 0.05, 0))
    assert inline.characters == (me,)
    me.remove()
    assert inline.characters == ()


def test_a_framed_character_is_stepped_by_the_frame(inline):
    inline.add_static(None, proxy=floor())
    me = inline.add_character(position=(0, 0.05, 0))
    assert me.framed is True
    me.set_move((1, 0, 0))
    for _ in range(30):
        inline.frame(1 / 60)
    assert me.position[0] > 0.5


def test_a_character_its_owner_steps_is_moved_by_the_ticks_the_frame_runs(inline):
    inline.add_static(None, proxy=floor())
    me = inline.add_character(position=(0, 0.05, 0))
    me.framed = False
    me.set_move((1, 0, 0))
    for _ in range(30):
        inline.frame(1 / 60)
    # The world thread moves every character in each tick the frame runs.
    assert me.position[0] > 0.5
    start = float(me.position[0])
    for _ in range(30):
        me.update(1 / 60)
    assert me.position[0] > start + 0.5


def test_a_platform_over_an_owned_character_steps_it_on_update(inline):
    inline.add_static(None, proxy=floor())
    me = inline.add_character(position=(0, 0.05, 0))
    me.framed = False
    platform = PhysicsViewPlatform.over(me)
    platform.set_move(forward=1.0)
    for _ in range(30):
        inline.frame(1 / 60)
        platform.update(1 / 60)
    assert me.position[2] < -0.5


def test_a_platform_over_a_framed_character_leaves_the_stepping_to_the_frame(inline):
    inline.add_static(None, proxy=floor())
    me = inline.add_character(position=(0, 0.05, 0))
    platform = PhysicsViewPlatform.over(me)
    platform.set_move(forward=1.0)
    for _ in range(30):
        platform.update(1 / 60)
    assert me.position[2] == pytest.approx(0.0)


def test_binding_a_platform_over_a_character_moves_the_body_the_world_sees(inline):
    inline.add_static(None, proxy=floor())
    me = inline.add_character(position=(0, 0.05, 0))
    me.framed = False
    platform = PhysicsViewPlatform.over(me)
    assert platform.bind_eye((20.0, 1.6, 0.0)) is not False
    # The character's capsule in the world is moved to it inside a tick.
    me.update(1 / 120)
    hit = inline.raycast((10.0, 1.0, 0.0), (1.0, 0.0, 0.0), 30.0)
    assert hit is not None and hit.body is me.body
    assert me.position[0] == pytest.approx(20.0, abs=0.01)
