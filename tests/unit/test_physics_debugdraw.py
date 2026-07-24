"""Wireframe debug overlay for the physics world (:mod:`OpenGLContext.physics.debugdraw`).

``PhysicsDebugDraw`` builds an ``IndexedLineSet`` overlay (plus an instanced set of
per-body proxy Transforms) from the live world state each frame. Overlay
construction is pure scenegraph/numpy work -- no GL context -- so these tests drive
a real :class:`omi_physics.world.PhysicsWorld` with box, sphere, capsule, convex
and trimesh bodies, real contacts and real joint constraints, then assert on the
geometry the overlay emits: vertex/colour counts, segment structure, per-feature
colouring, and the standalone wireframe generators.
"""
import numpy as np
import pytest

from omi_physics import body as _body
from omi_physics import model
from omi_physics.joints import PointConstraint, DistanceConstraint

from OpenGLContext.physics.demo import DemoScene
from OpenGLContext.physics import debugdraw
from OpenGLContext.physics.debugdraw import (
    PhysicsDebugDraw, PROXIES, AABBS, CONTACTS, VELOCITY, ACCELERATION,
    ANGULAR, JOINTS, ALL, C_CONTACT, C_AABB, C_VELOCITY, C_JOINT,
    box_edges_aabb, proxy_corners, proxy_edges, _unit_box_wire, _unit_sphere_wire,
)


def _stacked_scene():
    """A box dropped onto a static floor box, stepped until they touch (contacts).

    Stops the moment contacts appear so the dynamic box has not yet slept (a
    sleeping body clears its contacts), keeping the overlay's contact path live.
    """
    scene = DemoScene(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)),
                      debug_flags=0)
    scene.add_box(size=(20, 1, 20), position=(0, -0.5, 0), dynamic=False)
    scene.add_box(size=(1, 1, 1), position=(0, 0.55, 0), dynamic=True)
    for _ in range(300):
        scene.advance(1 / 120)
        if len(scene.world.contacts):
            break
    return scene


def test_proxies_build_one_transform_per_box_and_sphere():
    """Enabling PROXIES creates a per-body Transform under the proxy group."""
    scene = DemoScene(debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 3, 0))
    scene.add_sphere(radius=0.5, position=(2, 3, 0))
    dbg = PhysicsDebugDraw(scene.world, flags=PROXIES)
    dbg.update()
    assert len(dbg._proxy_group.children) == 2
    # a box proxy scales the shared unit box to its size
    box_tr = dbg._proxy_nodes[0][0]
    assert tuple(box_tr.scale) == pytest.approx((1.0, 1.0, 1.0))


def test_proxy_transforms_track_moving_bodies():
    """A second update writes the fallen body's new pose onto its proxy Transform."""
    scene = DemoScene(debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 10, 0))
    dbg = PhysicsDebugDraw(scene.world, flags=PROXIES)
    dbg.update()
    y0 = float(dbg._proxy_nodes[0][0].translation[1])
    for _ in range(60):
        scene.advance(1 / 120)
    dbg.update()
    y1 = float(dbg._proxy_nodes[0][0].translation[1])
    assert y1 < y0                                   # proxy followed the fall


def test_disabling_proxies_clears_the_group():
    """Turning PROXIES off after it built nodes empties the proxy group."""
    scene = DemoScene(debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 3, 0))
    dbg = PhysicsDebugDraw(scene.world, flags=PROXIES)
    dbg.update()
    assert dbg._proxy_nodes
    dbg.flags = CONTACTS                             # proxies now off
    dbg.update()
    assert dbg._proxy_group.children == []
    assert dbg._proxy_nodes == {}


def test_proxy_update_on_empty_world_is_a_noop():
    """PROXIES on a world with no bodies adds nothing."""
    scene = DemoScene(debug_flags=0)
    dbg = PhysicsDebugDraw(scene.world, flags=PROXIES)
    dbg.update()
    assert dbg._proxy_group.children == []


def test_proxy_skips_body_without_collider_or_trigger_shape():
    """A body carrying neither a collider nor a trigger shape gets no proxy."""
    scene = DemoScene(debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 3, 0))
    scene.world.add_body(model.Motion(type=model.DYNAMIC), position=(2, 3, 0))
    dbg = PhysicsDebugDraw(scene.world, flags=PROXIES)
    dbg.update()
    assert len(dbg._proxy_group.children) == 1       # only the collidered box


def test_sleeping_body_proxy_pose_is_not_rewritten():
    """A sleeping dynamic body's proxy Transform is left untouched on later updates."""
    scene = DemoScene(gravity=model.Gravity(gravity=0.0), debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 0, 0))
    dbg = PhysicsDebugDraw(scene.world, flags=PROXIES)
    dbg.update()
    for _ in range(240):
        scene.advance(1 / 120)
        if not scene.world.awake[0]:
            break
    assert not scene.world.awake[0]                  # asleep
    dbg.update()
    tr = dbg._proxy_nodes[0][0]
    scene.world.position[0] = (5, 5, 5)              # move it in the world
    dbg.update()                                     # sleeping -> pose skipped
    assert not np.allclose(tr.translation, (5, 5, 5))


def test_capsule_proxy_is_skipped_by_instanced_path():
    """A capsule has no shared unit wireframe, so it yields no proxy Transform."""
    scene = DemoScene(debug_flags=0)
    scene.add_mesh_body(geometry=None, shape=model.Shape.capsule(0.3, 2.0),
                        position=(0, 3, 0))
    dbg = PhysicsDebugDraw(scene.world, flags=PROXIES)
    dbg.update()
    assert dbg._proxy_group.children == []


def test_no_features_collapses_to_empty_overlay():
    """With nothing enabled the dynamic ILS collapses to a single dummy point."""
    scene = DemoScene(debug_flags=0)
    scene.add_box(position=(0, 3, 0))
    dbg = PhysicsDebugDraw(scene.world, flags=0)
    dbg.update()
    assert np.asarray(dbg.coord.point).shape == (1, 3)
    assert np.allclose(dbg.coord.point, [(0, 0, 0)])
    assert list(dbg.lines.coordIndex) == []


def test_contacts_draw_a_red_normal_per_contact():
    """Each world contact emits one red line segment along its normal."""
    scene = _stacked_scene()
    assert len(scene.world.contacts) > 0
    dbg = PhysicsDebugDraw(scene.world, flags=CONTACTS)
    dbg.update()
    n = len(scene.world.contacts)
    assert len(dbg.coord.point) == 2 * n             # two endpoints per contact
    assert all(tuple(c) == pytest.approx(C_CONTACT) for c in dbg.color.color)


def test_aabb_overlay_has_twelve_edges_per_body():
    """The AABB overlay draws the 12 box edges (24 endpoints) for each body."""
    scene = DemoScene(debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 3, 0))
    dbg = PhysicsDebugDraw(scene.world, flags=AABBS)
    dbg.update()
    assert len(dbg.coord.point) == 24
    assert all(tuple(c) == pytest.approx(C_AABB) for c in dbg.color.color)


def test_velocity_vector_points_along_motion():
    """The velocity line runs from the body position toward its linear velocity."""
    scene = DemoScene(debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 3, 0), velocity=(2, 0, 0))
    dbg = PhysicsDebugDraw(scene.world, flags=VELOCITY, vector_scale=0.5)
    dbg.update()
    pts = list(dbg.coord.point)
    assert len(pts) == 2
    tip = np.asarray(pts[1]) - np.asarray(pts[0])
    assert tip[0] > 0 and abs(tip[1]) < 1e-9         # +x, scaled velocity
    assert all(tuple(c) == pytest.approx(C_VELOCITY) for c in dbg.color.color)


def test_acceleration_vector_drawn_only_for_dynamic_bodies():
    """A dynamic body gets a gravity acceleration line; a static one does not."""
    scene = DemoScene(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)),
                      debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 5, 0), dynamic=True)
    scene.add_box(size=(1, 1, 1), position=(0, -1, 0), dynamic=False)
    dbg = PhysicsDebugDraw(scene.world, flags=ACCELERATION)
    dbg.update()
    assert len(dbg.coord.point) == 2                 # only the dynamic body
    tip = np.asarray(dbg.coord.point[1]) - np.asarray(dbg.coord.point[0])
    assert tip[1] < 0                                # points down (gravity)


def test_angular_vectors_appear_only_when_spinning():
    """Spin lines are drawn at each corner when angular velocity is non-zero."""
    scene = DemoScene(debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 3, 0))
    scene.world.angular_velocity[0] = (0, 5.0, 0)
    dbg = PhysicsDebugDraw(scene.world, flags=ANGULAR)
    dbg.update()
    spinning = len(dbg.coord.point)
    assert spinning == 16                            # 8 box corners, 2 pts each

    scene.world.angular_velocity[0] = (0, 0, 0)
    dbg.update()
    assert len(dbg.coord.point) == 1                 # no spin -> empty overlay


def test_joint_line_between_two_body_anchors():
    """A point constraint between two bodies draws one yellow line between them."""
    scene = DemoScene(gravity=model.Gravity(gravity=9.81), debug_flags=0)
    a = scene.add_box(size=(1, 1, 1), position=(0, 5, 0), dynamic=False)
    b = scene.add_box(size=(1, 1, 1), position=(0, 2, 0), dynamic=True)
    scene.world.add_joint_constraint(
        PointConstraint(a.index, b.index, anchor=(0, 3.5, 0)))
    dbg = PhysicsDebugDraw(scene.world, flags=JOINTS)
    dbg.update()
    assert len(dbg.coord.point) == 2
    assert all(tuple(c) == pytest.approx(C_JOINT) for c in dbg.color.color)
    assert np.allclose(dbg.coord.point[0], scene.world.position[a.index])
    assert np.allclose(dbg.coord.point[1], scene.world.position[b.index])


def test_joint_line_uses_world_anchor_when_pinned_to_world():
    """When a constraint pins body a to the world (a<0) the line starts at its anchor."""
    scene = DemoScene(gravity=model.Gravity(gravity=9.81), debug_flags=0)
    b = scene.add_box(size=(1, 1, 1), position=(0, 2, 0), dynamic=True)
    dbg = PhysicsDebugDraw(scene.world, flags=JOINTS)
    scene.world.add_joint_constraint(
        PointConstraint(-1, b.index, anchor=(1, 6, 0)))
    dbg.update()
    assert np.allclose(dbg.coord.point[0], (1, 6, 0))     # world anchor endpoint
    # a distance constraint anchored to the world on side b draws anchor_b
    scene.world.joint_constraints.clear()
    scene.world.add_joint_constraint(
        DistanceConstraint(b.index, -1, anchor_a=(0, 2, 0), anchor_b=(3, 3, 3)))
    dbg.update()
    assert np.allclose(dbg.coord.point[1], (3, 3, 3))


def test_joint_line_skips_constraints_without_endpoints():
    """A constraint object exposing no a/b indices contributes no line."""
    class _Bare:
        pass
    scene = DemoScene(debug_flags=0)
    scene.world.joint_constraints.append(_Bare())
    dbg = PhysicsDebugDraw(scene.world, flags=JOINTS)
    dbg.update()
    assert np.asarray(dbg.coord.point).shape == (1, 3)   # nothing drawn


def test_all_features_combine_into_one_overlay():
    """ALL flags together produce a non-trivial overlay and proxy transforms."""
    scene = _stacked_scene()
    dbg = PhysicsDebugDraw(scene.world, flags=ALL)
    dbg.update()
    assert len(dbg.coord.point) > 1
    assert len(dbg.color.color) == len(dbg.coord.point)
    assert len(dbg._proxy_group.children) >= 1


# ── standalone geometry generators ──────────────────────────────────────
def test_box_edges_aabb_returns_twelve_edges():
    edges = box_edges_aabb(np.array([-1, -2, -3.0]), np.array([1, 2, 3.0]))
    assert len(edges) == 12
    for a, b in edges:                                # every corner in range
        assert np.all(a >= -3) and np.all(b <= 3)


def test_proxy_edges_and_corners_per_shape_type():
    """Each proxy kind yields wireframe edges and corner points."""
    shapes = {
        'box': model.Shape.box((1, 2, 3)),
        'sphere': model.Shape.sphere(0.7),
        'capsule': model.Shape.capsule(0.3, 2.0),
        'convex': model.Shape.convex(np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype='d')),
    }
    for shape in shapes.values():
        proxy = _body.make_proxy(shape, (0, 0, 0), (0, 0, 0, 1))
        assert len(proxy_edges(proxy)) > 0
        assert len(proxy_corners(proxy)) > 0


def test_proxy_edges_for_trimesh():
    """A triangle-mesh proxy yields three edges per triangle."""
    pts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype='d')
    idx = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype='i')
    proxy = _body.make_proxy(model.Shape.trimesh(pts, idx), (0, 0, 0), (0, 0, 0, 1))
    edges = proxy_edges(proxy)
    assert len(edges) == 4 * 3                        # 4 tris, 3 edges each


def test_proxy_edges_empty_for_unsupported_proxy():
    """A proxy kind the overlay does not tessellate (a bare triangle) yields no edges."""
    tri = _body.TriangleProxy((0, 0, 0), (1, 0, 0), (0, 1, 0))
    assert proxy_edges(tri) == []


def test_unit_wireframes_have_expected_edge_counts():
    """The shared unit box wireframe has 12 edges; the sphere three 16-seg rings."""
    box = _unit_box_wire()
    assert len(box.coordIndex) == 12 * 3              # [a, b, -1] per edge
    sphere = _unit_sphere_wire()
    assert len(sphere.coordIndex) == 3 * 16 * 3       # three rings of 16 segments


def test_hull_edges_are_unique():
    """Convex-hull edges are de-duplicated across shared faces."""
    pts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype='d')
    edges = debugdraw._hull_edges(pts)
    assert 0 < len(edges) <= 6                        # tetra has 6 unique edges


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
