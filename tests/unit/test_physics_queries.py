"""Ray casts, sweeps and overlap tests against a physics service, in both modes.

A query answers in the call, on the calling thread. Inline it reads the live
world; on a thread it reads a copy of the bodies the render thread keeps.
"""
import threading
import time

import numpy as np
import pytest

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

pytestmark = pytest.mark.engines('omi', 'jolt')

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def block(size, at=(0, 0, 0)):
    return surfaces.shape(surfaces.block(size), LOOK, translation=at)


def ball(radius=0.5, at=(0, 3, 0)):
    return surfaces.shape(surfaces.sphere(radius), LOOK, translation=at)


@pytest.fixture(params=['inline', 'thread'])
def physics(request):
    service = Physics(PhysicsDefinition(mode=request.param, maxCatchUp=2.0, tickHz=100.0))
    yield service
    service.close()


def test_a_ray_down_hits_the_floor_with_the_body_the_point_and_the_normal(physics):
    floor = physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    hit = physics.raycast((0, 5, 0), (0, -1, 0))
    assert hit is not None and hit.body is floor
    assert hit.distance == pytest.approx(5.0, abs=1e-6)
    assert hit.point == pytest.approx((0, 0, 0), abs=1e-6)
    assert hit.normal == pytest.approx((0, 1, 0), abs=1e-6)


def test_a_ray_that_misses_answers_none(physics):
    physics.add_static(block((2, 1, 2), at=(0, -0.5, 0)))
    assert physics.raycast((10, 5, 0), (0, -1, 0)) is None


def test_max_distance_limits_the_ray(physics):
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    assert physics.raycast((0, 5, 0), (0, -1, 0), max_distance=2.0) is None


def test_skip_leaves_a_body_out_of_the_answer(physics):
    near = physics.add_static(block((4, 1, 4), at=(0, 1.5, 0)))
    far = physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    assert physics.raycast((0, 5, 0), (0, -1, 0)).body is near
    assert physics.raycast((0, 5, 0), (0, -1, 0), skip=near).body is far
    assert physics.raycast((0, 5, 0), (0, -1, 0), skip=[near, far]) is None


def test_a_body_added_a_moment_ago_is_hit_without_a_frame_between(physics):
    body = physics.add_static(block((4, 1, 4), at=(0, 0, 0)))
    assert physics.raycast((0, 5, 0), (0, -1, 0)).body is body


def test_a_removed_body_is_not_hit(physics):
    body = physics.add_static(block((4, 1, 4), at=(0, 0, 0)))
    body.remove()
    assert physics.raycast((0, 5, 0), (0, -1, 0)) is None


def test_a_dynamic_body_is_hit_where_it_was_last_published(physics):
    node = ball(0.5, at=(0, 6, 0))
    body = physics.add_dynamic(node)
    body.set_velocity((0, 0, 0))
    physics.gravity = (0, 0, 0)
    physics.frame(0.02)
    hit = physics.raycast((0, 10, 0), (0, -1, 0))
    assert hit is not None and hit.body is body
    assert hit.distance == pytest.approx(3.5, abs=0.05)


def test_a_dynamic_body_that_moved_is_hit_where_it_is_now(physics):
    node = ball(0.5, at=(0, 6, 0))
    body = physics.add_dynamic(node)
    physics.gravity = (0, 0, 0)
    body.set_transform(translation=(20, 6, 0))
    deadline = time.monotonic() + 5.0
    hit = None
    while hit is None and time.monotonic() < deadline:
        physics.frame(0.02)
        time.sleep(0.01)
        hit = physics.raycast((20, 10, 0), (0, -1, 0))
    assert hit is not None and hit.body is body


def test_a_trimesh_hit_names_the_triangle(physics):
    floor = block((20, 1, 20), at=(0, -0.5, 0))
    body = physics.add_static(floor, proxy='trimesh')
    hit = physics.raycast((1, 5, 1), (0, -1, 0))
    assert hit.body is body and hit.triangle >= 0


def test_raycast_many_answers_each_ray_in_order(physics):
    floor = physics.add_static(block((4, 1, 4), at=(0, -0.5, 0)))
    origins = [(0, 5, 0), (1, 5, 1), (50, 5, 0)]
    hits = physics.raycast_many(origins, [(0, -1, 0)] * 3)
    assert [h.body if h else None for h in hits] == [floor, floor, None]


def test_a_sphere_swept_along_the_floor_stops_at_the_wall(physics):
    physics.add_static(block((1, 4, 10), at=(5, 2, 0)))
    distance = physics.sweep_sphere((0, 1, 0), (1, 0, 0), 10.0, 0.5)
    assert distance == pytest.approx(4.0, abs=0.05)         # the wall's face at 4.5, less the radius


def test_a_wide_sphere_stops_sooner_than_a_narrow_one(physics):
    physics.add_static(block((1, 4, 10), at=(5, 2, 0)))
    narrow = physics.sweep_sphere((0, 1, 0), (1, 0, 0), 10.0, 0.1)
    wide = physics.sweep_sphere((0, 1, 0), (1, 0, 0), 10.0, 0.9)
    assert narrow > wide


def test_a_sweep_in_the_clear_answers_none(physics):
    physics.add_static(block((1, 4, 10), at=(5, 2, 0)))
    assert physics.sweep_sphere((0, 1, 0), (-1, 0, 0), 10.0, 0.5) is None


def test_a_sweep_that_starts_inside_a_body_answers_zero(physics):
    physics.add_static(block((4, 4, 4), at=(0, 0, 0)), proxy='box')
    assert physics.sweep_sphere((0, 0, 0), (1, 0, 0), 10.0, 0.5) == pytest.approx(0.0)


def test_overlap_lists_the_bodies_a_shape_touches(physics):
    near = physics.add_static(block((2, 2, 2), at=(0, 0, 0)))
    physics.add_static(block((2, 2, 2), at=(10, 0, 0)))
    touching = physics.overlap(Proxy.sphere(1.0), (1.5, 0, 0))
    assert touching == [near]


def test_overlap_of_empty_space_is_empty(physics):
    physics.add_static(block((2, 2, 2), at=(0, 0, 0)))
    assert physics.overlap(Proxy.sphere(0.5), (0, 20, 0)) == []


def test_overlap_takes_a_turn(physics):
    bar = physics.add_static(block((6, 0.2, 0.2), at=(0, 0, 0)), proxy='box')
    probe = Proxy.box((0.2, 0.2, 0.2))
    assert physics.overlap(probe, (2.5, 0, 0)) == [bar]
    assert physics.overlap(probe, (0, 0, 2.5), rotation=(0, 1, 0, np.pi / 2)) == []


def test_queries_from_this_thread_are_safe_while_the_worker_steps():
    service = Physics(PhysicsDefinition(mode='thread', maxCatchUp=2.0, tickHz=200.0))
    try:
        service.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
        for number in range(8):
            service.add_dynamic(ball(0.3, at=(number - 4, 2 + number, 0)))
        failures = []

        def cast():
            try:
                for _ in range(200):
                    service.raycast((0, 20, 0), (0, -1, 0))
                    service.sweep_sphere((0, 1, 0), (1, 0, 0), 5.0, 0.3)
                    service.frame(0.005)
            except Exception as error:      # pragma: no cover - the failure being looked for
                failures.append(error)

        thread = threading.Thread(target=cast)
        thread.start()
        thread.join()
        assert failures == []
    finally:
        service.close()


@pytest.mark.engines('omi', reason="counts the omi engine's query proxies")
def test_a_body_that_has_not_moved_is_not_made_into_a_proxy_again_by_the_next_query(
        physics, monkeypatch):
    from OpenGLContext.physics import queries

    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)), proxy=Proxy.trimesh(
        np.array([[-10, 0, -10], [10, 0, -10], [10, 0, 10], [-10, 0, 10]], dtype='d'),
        np.array([[0, 2, 1], [0, 3, 2]])))
    built = []
    real = queries.make_proxy
    monkeypatch.setattr(queries, 'make_proxy',
                        lambda shape, *pose: built.append(shape.type) or real(shape, *pose))
    first = physics.sweep_sphere((0, 3, 0), (0, -1, 0), 5.0, 0.25)
    made = len(built)
    second = physics.sweep_sphere((0, 4, 0), (0, -1, 0), 6.0, 0.25)
    assert first == pytest.approx(3.25, abs=0.01)
    assert second == pytest.approx(4.25, abs=0.01)
    assert made >= 1
    assert len(built) == made
    assert physics.overlap(Proxy.sphere(0.5), (0, -0.3, 0))
    assert len(built) == made + 1                              # the probe, which is new each time
