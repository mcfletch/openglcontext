"""``PhysicsManager.attach``: a scenegraph node made a physics body.

The collision shape is cooked from what the node draws, so these build nodes
from the engine's own surfaces and read back what the world holds.
"""
import numpy as np
import pytest
from omi_physics import model

from OpenGLContext.physics.gltf_world import node_mesh
from OpenGLContext.physics.manager import PhysicsManager
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import Transform
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def block(size, at=(0, 0, 0)):
    return surfaces.shape(surfaces.block(size), LOOK, translation=at)


def ball(radius, at=(0, 0, 0)):
    return surfaces.shape(surfaces.sphere(radius), LOOK, translation=at)


@pytest.fixture
def manager():
    return PhysicsManager(default_linear_damping=0.0)


def shape_of(manager, body):
    return manager.world.shapes[manager.world.collider_shape[body.index]]


class TestNodeMesh:
    def test_a_node_draws_its_children_in_its_own_frame(self):
        node = block((2, 4, 6), at=(10, 20, 30))
        points, indices = node_mesh(node)
        assert points.min(axis=0) == pytest.approx((-1, -2, -3))
        assert points.max(axis=0) == pytest.approx((1, 2, 3))
        assert indices.shape[1] == 3

    def test_the_nodes_scale_is_applied_to_what_it_draws(self):
        node = block((2, 2, 2))
        node.scale = (1, 3, 1)
        points, _ = node_mesh(node)
        assert points.max(axis=0) == pytest.approx((1, 3, 1))

    def test_a_node_with_nothing_to_draw_has_no_mesh(self):
        assert node_mesh(Transform()) is None


class TestAttach:
    def test_a_box_becomes_a_static_box_body_where_it_stands(self, manager):
        node = block((2, 4, 6), at=(1, 2, 3))
        body = manager.attach(node, strategy='primitive')
        shape = shape_of(manager, body)
        assert shape.type == 'box'
        assert tuple(shape.size) == pytest.approx((2, 4, 6))
        assert tuple(manager.world.position[body.index]) == pytest.approx((1, 2, 3))
        assert body.motion.type == model.STATIC

    def test_a_sphere_becomes_a_sphere(self, manager):
        body = manager.attach(ball(0.3), model.Motion(type=model.DYNAMIC, mass=5.0),
                              strategy='primitive')
        shape = shape_of(manager, body)
        assert shape.type == 'sphere'
        assert shape.radius == pytest.approx(0.3, abs=0.01)

    def test_a_dynamic_body_moves_the_node_it_is_bound_to(self, manager):
        node = ball(0.3, at=(0, 5, 0))
        manager.attach(node, model.Motion(type=model.DYNAMIC), strategy='primitive')
        manager.advance(0.5)
        assert node.translation[1] < 5.0

    def test_a_dynamic_ball_lands_on_an_attached_floor(self, manager):
        manager.attach(block((20, 1, 20), at=(0, -0.5, 0)), material='wood',
                       strategy='primitive')
        node = ball(0.5, at=(0, 3, 0))
        manager.attach(node, model.Motion(type=model.DYNAMIC), material='rubber',
                       strategy='primitive')
        for _ in range(240):
            manager.advance(1 / 60)
        assert node.translation[1] == pytest.approx(0.5, abs=0.1)

    def test_a_trigger_reports_what_enters_it_and_stops_nothing(self, manager):
        pad = manager.attach(block((4, 1, 4), at=(0, 0.5, 0)), trigger=True,
                             strategy='primitive')
        entered = []
        manager.events.subscribe(entered.append, body=pad, kinds=('trigger',),
                                 phases=('enter',))
        falling = ball(0.3, at=(0, 4, 0))
        manager.attach(falling, model.Motion(type=model.DYNAMIC), strategy='primitive')
        for _ in range(120):
            manager.advance(1 / 60)
        assert len(entered) == 1
        assert falling.translation[1] < 0.0       # nothing solid held it up

    def test_material_names_are_added_to_the_world_once(self, manager):
        manager.attach(block((1, 1, 1)), material='wood', strategy='primitive')
        manager.attach(block((1, 1, 1), at=(5, 0, 0)), material='wood', strategy='primitive')
        assert len(manager.world.materials) == 1

    def test_a_material_object_is_added_as_it_is(self, manager):
        slick = model.Material(staticFriction=0.0, dynamicFriction=0.0, restitution=0.9)
        body = manager.attach(block((1, 1, 1)), material=slick, strategy='primitive')
        index = manager.world.collider_material[body.index]
        assert manager.world.materials[index] is slick

    def test_a_node_that_draws_nothing_is_refused(self, manager):
        with pytest.raises(ValueError, match='draws no triangles'):
            manager.attach(Transform())

    def test_a_concave_dynamic_body_gets_its_hull(self, manager):
        outline = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]
        node = surfaces.shape(surfaces.prism(outline, 1.0), LOOK)
        body = manager.attach(node, model.Motion(type=model.DYNAMIC))
        assert shape_of(manager, body).type == 'convex'
        assert np.isfinite(manager.world.position[body.index]).all()

    def test_a_strategy_that_makes_several_shapes_is_refused(self, manager):
        outline = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]
        node = surfaces.shape(surfaces.prism(outline, 1.0), LOOK)
        with pytest.raises(ValueError, match='several shapes'):
            manager.attach(node, model.Motion(type=model.DYNAMIC), strategy='decompose')
