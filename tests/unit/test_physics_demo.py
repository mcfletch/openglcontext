"""Physics demo scene builder (:mod:`OpenGLContext.physics.demo`).

``DemoScene`` keeps a scenegraph and an ``omi_physics`` world in lockstep. These
tests drive the real builder -- adding spheres, mesh bodies, gravity volumes and
trigger boxes to a live :class:`omi_physics.world.PhysicsWorld` -- and assert on
the resulting world state and on :meth:`advance`'s redraw/settle signal, rather
than merely that the calls did not raise.
"""
import numpy as np
import pytest

from omi_physics import model
from omi_physics.gravity import SphereRegion

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.physics.demo import DemoScene, disable_vsync

#: integer motion-type code the world stores for a ``model.STATIC`` body
_STATIC_CODE = 0


def test_disable_vsync_swallows_a_raising_swap_interval(monkeypatch):
    """disable_vsync ignores any error from glfw.swap_interval (no current context)."""
    import glfw

    def _boom(_interval):
        raise RuntimeError('no current context')

    monkeypatch.setattr(glfw, 'swap_interval', _boom)
    disable_vsync()                                  # must not propagate the error


def test_raw_material_registers_a_custom_material():
    """raw_material adds a Material to the world and returns a valid index."""
    scene = DemoScene(debug_flags=0)
    idx = scene.raw_material(model.Material(dynamicFriction=0.9, restitution=0.1))
    assert isinstance(idx, int)
    assert scene.world.materials[idx].dynamicFriction == pytest.approx(0.9)


def test_add_sphere_creates_body_and_render_mesh():
    """add_sphere registers a dynamic body and appends a Sphere render node."""
    scene = DemoScene(debug_flags=0)
    body = scene.add_sphere(radius=0.75, position=(1, 4, 2))
    assert body.index == 0
    assert np.allclose(scene.world.position[0], (1, 4, 2))
    geom = scene.children[0].children[0].geometry
    assert isinstance(geom, basenodes.Sphere)
    assert geom.radius == pytest.approx(0.75)


def test_add_mesh_body_attaches_cooked_shape_to_arbitrary_geometry():
    """add_mesh_body binds an already-cooked Shape to a supplied render mesh."""
    scene = DemoScene(debug_flags=0)
    ifs = basenodes.IndexedFaceSet(
        coord=basenodes.Coordinate(point=[(0, 0, 0), (1, 0, 0), (0, 1, 0)]),
        coordIndex=[0, 1, 2, -1])
    shape = model.Shape.box((1, 1, 1))
    body = scene.add_mesh_body(geometry=ifs, shape=shape, position=(0, 2, 0),
                               dynamic=False)
    assert body.index == 0
    assert scene.world.motion_type[0] == _STATIC_CODE
    assert scene.children[0].children[0].geometry is ifs


def test_add_gravity_volume_registers_a_local_field():
    """add_gravity_volume pushes a GravityVolume into the world."""
    scene = DemoScene(debug_flags=0)
    before = len(scene.world.gravity_volumes)
    field = model.Gravity(gravity=5.0, direction=(0, 1, 0))
    scene.add_gravity_volume(field, region=SphereRegion(center=(0, 0, 0), radius=4.0))
    assert len(scene.world.gravity_volumes) == before + 1


def test_add_trigger_box_is_static_and_non_solid():
    """add_trigger_box adds a static trigger body with a trigger shape, no collider."""
    scene = DemoScene(debug_flags=0)
    body = scene.add_trigger_box(size=(2, 2, 2), position=(0, 1, 0))
    assert body.index == 0
    assert scene.world.motion_type[0] == _STATIC_CODE
    assert scene.world.trigger_shape[0] >= 0
    assert scene.world.collider_shape[0] < 0


def test_advance_reports_redraw_while_moving_then_settles():
    """advance returns True while a body moves and stops once everything sleeps."""
    scene = DemoScene(gravity=model.Gravity(gravity=0.0), debug_flags=0)
    scene.add_box(size=(1, 1, 1), position=(0, 0, 0))
    assert scene.advance(1 / 120) is True            # first frames: still active
    settled = False
    for _ in range(600):
        render = scene.advance(1 / 120)
        if not scene.world.awake[0] and render is False:
            settled = True
            break
    assert settled                                   # once asleep, stops redrawing


def test_scene_graph_includes_bodies_debug_and_background():
    """scene_graph assembles bodies, the debug overlay root and a background."""
    scene = DemoScene(debug_flags=0)
    scene.add_box(position=(0, 3, 0))
    graph = scene.scene_graph(extra=[basenodes.Group()])
    assert scene.children[0] in graph.children
    assert scene.debug.root in graph.children
    assert any(isinstance(c, basenodes.SimpleBackground) for c in graph.children)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
