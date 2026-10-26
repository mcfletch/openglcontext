"""Tests for the scenery a physics service makes static bodies of.

A shape that is in the scene and that no body claims is a static body once it
has been cooked. The cooking runs off the calling thread, so these wait for it.
"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.physics.gltf_world import iter_meshes, site_mesh
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def block(size, at=(0, 0, 0)):
    return surfaces.shape(surfaces.block(size), LOOK, translation=at)


def ball(radius=0.5, at=(0, 3, 0)):
    return surfaces.shape(surfaces.sphere(radius), LOOK, translation=at)


def scene_of(*children):
    return basenodes.sceneGraph(children=list(children))


def make(**named) -> Physics:
    named.setdefault('mode', 'inline')
    named.setdefault('maxCatchUp', 2.0)
    named.setdefault('tickHz', 100.0)
    return Physics(PhysicsDefinition(**named))


def settle(physics: Physics) -> None:
    assert physics.wait_cooked(20.0)
    physics.frame(0.0)


@pytest.fixture
def physics():
    service = make()
    yield service
    service.close()


def run_for(physics, seconds, frame=0.02):
    for _ in range(int(round(seconds / frame))):
        physics.frame(frame)


# -- walking the tree -------------------------------------------------------------

def test_iter_meshes_finds_each_shape_with_its_world_matrix():
    floor = block((2, 2, 2), at=(5, 0, 0))
    root = scene_of(floor)
    sites = list(iter_meshes(root))
    assert [site.node for site in sites] == [floor.children[0]]
    assert sites[0].world[3, 0] == pytest.approx(5.0)


def test_site_mesh_is_in_world_space():
    root = scene_of(block((2, 2, 2), at=(5, 0, 0)))
    points, tris = site_mesh(next(iter_meshes(root)))
    assert points.min(axis=0) == pytest.approx((4, -1, -1))
    assert points.max(axis=0) == pytest.approx((6, 1, 1))
    assert tris.shape[1] == 3


def test_iter_meshes_leaves_out_what_skip_names():
    floor, other = block((1, 1, 1)), block((1, 1, 1), at=(4, 0, 0))
    root = scene_of(floor, other)
    sites = list(iter_meshes(root, skip=lambda node: node is other))
    assert [site.node for site in sites] == [floor.children[0]]


def test_iter_meshes_leaves_out_a_disabled_collision_group():
    inside = block((1, 1, 1))
    root = scene_of(x3d.Collision(enabled=False, children=[inside]))
    assert list(iter_meshes(root)) == []


# -- making static bodies -------------------------------------------------------------

def test_a_shape_in_the_scene_stops_a_falling_ball(physics):
    floor = block((20, 1, 20), at=(0, -0.5, 0))
    node = ball(0.5, at=(0, 2, 0))
    physics.scenery_changed(scene_of(floor, node), 1)
    physics.add_dynamic(node, restitution=0.0)
    settle(physics)
    run_for(physics, 2.0)
    assert node.translation[1] == pytest.approx(0.5, abs=0.06)


def test_body_for_a_shape_answers_at_once_before_the_cooking_has_finished(physics):
    floor = block((20, 1, 20))
    physics.scenery_changed(scene_of(floor), 1)
    body = physics.body_for(floor.children[0])
    assert body is not None and body.kind == 'static' and body.alive


def test_the_same_scene_generation_is_not_looked_at_twice(physics):
    root = scene_of(block((1, 1, 1)))
    assert physics.scenery_changed(root, 1) == 1
    root.children.append(block((1, 1, 1), at=(5, 0, 0)))
    assert physics.scenery_changed(root, 1) == 0


def test_only_the_new_shape_is_cooked_when_the_scene_grows(physics):
    root = scene_of(block((1, 1, 1)))
    physics.scenery_changed(root, 1)
    root.children.append(block((1, 1, 1), at=(5, 0, 0)))
    assert physics.scenery_changed(root, 2) == 1


def test_a_shape_that_leaves_the_scene_loses_its_body(physics):
    kept, gone = block((1, 1, 1)), block((1, 1, 1), at=(5, 0, 0))
    root = scene_of(kept, gone)
    physics.scenery_changed(root, 1)
    settle(physics)
    body = physics.body_for(gone.children[0])
    root.children.remove(gone)
    physics.scenery_changed(root, 2)
    assert not body.alive
    assert physics.body_for(gone.children[0]) is None
    assert physics.body_for(kept.children[0]).alive


def test_a_shape_inside_a_body_is_not_scenery(physics):
    node = ball()
    root = scene_of(node)
    physics.add_dynamic(node)
    assert physics.scenery_changed(root, 1) == 0


def test_a_shape_marked_collide_false_is_left_out(physics):
    ghost = block((1, 1, 1))
    ghost.children[0].collide = False
    assert physics.scenery_changed(scene_of(ghost), 1) == 0


def test_a_shape_in_a_disabled_collision_group_is_left_out(physics):
    root = scene_of(x3d.Collision(enabled=False, children=[block((1, 1, 1))]))
    assert physics.scenery_changed(root, 1) == 0


def test_geometry_with_no_triangles_is_left_out_without_a_complaint(physics, caplog):
    points = basenodes.Shape(
        geometry=basenodes.PointSet(coord=basenodes.Coordinate(point=[(0, 0, 0)])))
    assert physics.scenery_changed(scene_of(points), 1) == 0
    assert caplog.text == ''


def test_explicit_colliders_derive_nothing():
    service = make(colliders='explicit')
    assert service.scenery_changed(scene_of(block((1, 1, 1))), 1) == 0
    service.close()


def test_no_colliders_derive_nothing():
    service = make(colliders='none')
    assert service.scenery_changed(scene_of(block((1, 1, 1))), 1) == 0
    service.close()


def test_a_scaled_parent_scales_the_collider(physics):
    from OpenGLContext.scenegraph.transform import Transform
    floor = block((1, 1, 1), at=(0, -0.5, 0))
    big = Transform(scale=(40, 1, 40), children=[floor])
    node = ball(0.5, at=(15, 2, 0))
    physics.scenery_changed(scene_of(big, node), 1)
    physics.add_dynamic(node, restitution=0.0)
    settle(physics)
    run_for(physics, 2.0)
    assert node.translation[1] == pytest.approx(0.5, abs=0.1)


def test_add_dynamic_on_a_node_already_derived_replaces_the_static_body(physics):
    floor = block((20, 1, 20), at=(0, -0.5, 0))
    node = ball(0.5, at=(0, 2, 0))
    root = scene_of(floor, node)
    physics.scenery_changed(root, 1)
    settle(physics)
    static_ball = physics.body_for(node.children[0])
    dynamic = physics.add_dynamic(node, restitution=0.0)
    assert not static_ball.alive
    assert physics.body_for(node) is dynamic
    run_for(physics, 2.0)
    assert node.translation[1] == pytest.approx(0.5, abs=0.06)


def test_a_handler_added_before_the_cooking_finishes_hears_the_landing(physics):
    floor = block((20, 1, 20), at=(0, -0.5, 0))
    node = ball(0.5, at=(0, 1.0, 0))
    physics.scenery_changed(scene_of(floor, node), 1)
    heard = []
    keep = heard.append
    physics.body_for(floor.children[0]).addEventHandler('hit', function=keep)
    physics.add_dynamic(node, restitution=0.0)
    settle(physics)
    run_for(physics, 1.0)
    assert len(heard) == 1


def test_wait_cooked_says_when_the_cooking_is_done(physics):
    physics.scenery_changed(scene_of(block((1, 1, 1))), 1)
    assert physics.wait_cooked(20.0) is True
    assert physics.cooking == 0


def test_a_scene_of_many_shapes_costs_nothing_per_frame_once_it_is_made(physics):
    root = scene_of(*[block((1, 1, 1), at=(index * 3, 0, 0)) for index in range(40)])
    physics.scenery_changed(root, 1)
    settle(physics)
    cooked = physics.cooked
    for _ in range(5):
        assert physics.scenery_changed(root, 1) == 0
    assert physics.cooked == cooked == 40
    assert np.all([physics.frame(0.02) is False for _ in range(3)])


def test_a_place_made_while_the_body_cooks_is_read_back_and_reaches_the_world(physics):
    floor = block((20, 1, 20))
    physics.scenery_changed(scene_of(floor), 1)
    body = physics.body_for(floor.children[0])
    body.set_transform((0.0, -3.0, 0.0))
    assert body.position == pytest.approx((0.0, -3.0, 0.0))
    settle(physics)
    assert body.position == pytest.approx((0.0, -3.0, 0.0))
    hit = physics.raycast((0, 10, 0), (0, -1, 0), 20.0)
    assert hit is not None and hit.point[1] == pytest.approx(-2.5, abs=0.01)


def test_a_world_held_inline_waits_for_its_scenery_before_it_steps(physics, monkeypatch):
    import time  # noqa: PLC0415 only this case sleeps

    from OpenGLContext.physics.colliders import SceneryTracker  # noqa: PLC0415 only this case slows the cooking

    cook = SceneryTracker._spec

    def slow(body, site, mesh):
        time.sleep(0.3)
        return cook(body, site, mesh)

    monkeypatch.setattr(SceneryTracker, '_spec', staticmethod(slow))
    physics.pin_inline(True)
    floor = block((20, 1, 20), at=(0, -0.5, 0))
    physics.scenery_changed(scene_of(floor), 1)
    physics.frame(0.02)
    assert physics.cooking == 0
    assert physics.body_for(floor.children[0]).uid in physics.worker.runtime
