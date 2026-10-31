"""The trunks and rocks a free-fly camera is held out of, and the avatar is stopped by.

:meth:`~OpenGLContext.move.terrainwalk.TerrainWalkMixin.collide_and_clamp` seats
the free-fly camera on the ground and out of the colliders it moved into, using
the same bodies the walking avatar meets. The cases are the ones a hand-written
scan of every trunk would have to get right: a camera inside a trunk, on its
axis, between two, in a move longer than a trunk is wide, and nowhere near one.
"""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain import HeightField

from ._terrain_host import Clock, eye, flat_field, run


@pytest.fixture
def clock():
    made = Clock()
    yield made
    made.restore()


def level(extent=200.0, relief=10.0):
    return HeightField(np.zeros((16, 16)), extent, relief)


def camera_at(clock, field, trunks=None, radii=None, at=(0.0, 0.0, 0.0)):
    """A free-fly host with the camera at ``at``, bound to ``field`` and not yet walking."""
    host = clock.host(at)
    host.init_walk(field, trunks, radii)
    return host


def settled(host, x, z):
    """Put the free-fly camera at ``(x, z)`` and seat it; the xz it ends at."""
    host.platform.setPosition((x, 0.0, z))
    host.collide_and_clamp()
    return eye(host)[0], eye(host)[2]


def clear_of(trunks, radii, host, x, z, slack=0.02):
    return all(math.hypot(x - t[0], z - t[2]) >= r + host.player_radius - slack
               for t, r in zip(trunks, radii, strict=True))


def field_of_trunks(n, seed, spread=40.0, rmin=0.2, rmax=0.8):
    rng = np.random.default_rng(seed)
    positions = np.zeros((n, 3), np.float32)
    positions[:, 0] = rng.uniform(-spread, spread, n)
    positions[:, 2] = rng.uniform(-spread, spread, n)
    return positions, rng.uniform(rmin, rmax, n).astype(np.float32)


# -- trunks ---------------------------------------------------------------------

def test_a_camera_inside_a_trunk_is_put_out_of_it_along_the_line_from_its_axis(clock):
    trunk = np.array([[10.0, 0.0, 20.0]], np.float32)
    radius = np.array([0.3], np.float32)
    host = camera_at(clock, level(), trunk, radius)
    x, z = settled(host, 10.1, 20.0)
    assert math.hypot(x - 10.0, z - 20.0) == pytest.approx(0.3 + host.player_radius, abs=0.02)
    assert z == pytest.approx(20.0, abs=0.02) and x > 10.1


def test_a_camera_is_put_out_of_a_trunk_wherever_it_is_inside_it(clock):
    for seed in range(12):
        positions, radii = field_of_trunks(1, seed)
        rng = np.random.default_rng(seed)
        angle = rng.uniform(0.0, 2.0 * math.pi)
        reach = 0.4 * (radii[0] + 0.25)
        host = camera_at(clock, level(), positions, radii)
        x, z = settled(host, positions[0, 0] + reach * math.cos(angle),
                       positions[0, 2] + reach * math.sin(angle))
        assert clear_of(positions, radii, host, x, z), seed


def test_a_camera_on_the_axis_of_a_trunk_is_put_out_of_it(clock):
    trunk = np.array([[3.0, 0.0, -2.0]], np.float32)
    radius = np.array([0.5], np.float32)
    host = camera_at(clock, level(), trunk, radius)
    x, z = settled(host, 3.0, -2.0)
    assert clear_of(trunk, radius, host, x, z)


def test_a_camera_between_trunks_ends_clear_of_all_of_them(clock):
    trunks = np.array([[0, 0, 0], [1.2, 0, 0], [-1.2, 0, 0]], np.float32)
    radii = np.array([0.5, 0.9, 0.9], np.float32)
    for x in np.linspace(-2.0, 2.0, 17):
        host = camera_at(clock, level(), trunks, radii)
        settled_x, settled_z = settled(host, float(x), 0.0)
        # The gap between the outer trunks and the middle one is narrower than the avatar:
        # it is put beside them, never inside one.
        assert clear_of(trunks, radii, host, settled_x, settled_z, slack=0.05), x


def test_a_camera_clear_of_the_trunks_is_not_moved(clock):
    trunk = np.array([[10.0, 0.0, 20.0]], np.float32)
    host = camera_at(clock, level(), trunk, np.array([0.3], np.float32))
    assert settled(host, 15.0, 20.0) == pytest.approx((15.0, 20.0), abs=1e-6)


def test_a_camera_far_from_every_trunk_is_not_moved(clock):
    positions, radii = field_of_trunks(50, 7)
    host = camera_at(clock, level(), positions, radii)
    assert settled(host, 90.0, 90.0) == pytest.approx((90.0, 90.0), abs=1e-6)


def test_no_trunks_are_no_obstacle(clock):
    for trunks, radii in ((None, None), (np.zeros((0, 3), np.float32), np.zeros(0, np.float32))):
        host = camera_at(clock, level(), trunks, radii)
        assert settled(host, 1.0, 2.0) == pytest.approx((1.0, 2.0), abs=1e-6)


def test_trunks_with_no_radius_are_posts_the_camera_is_put_out_of(clock):
    rng = np.random.default_rng(3)
    positions = np.zeros((60, 3), np.float32)
    positions[:, 0] = rng.uniform(-20, 20, 60)
    positions[:, 2] = rng.uniform(-20, 20, 60)
    host = camera_at(clock, level(), positions, None)
    x, z = settled(host, float(positions[0, 0]) + 0.01, float(positions[0, 2]))
    assert clear_of(positions, np.full(60, 0.05), host, x, z, slack=0.05)


def test_the_camera_is_seated_on_the_ground_under_it(clock):
    field = HeightField(np.linspace(0.0, 1.0, 17)[None, :] * np.ones((17, 1)), 200.0, 30.0)
    host = camera_at(clock, field)
    host.platform.setPosition((10.0, -999.0, -3.0))
    host.collide_and_clamp()
    assert eye(host)[1] == pytest.approx(field.height_at(10.0, -3.0) + host.eye_height, abs=0.02)


# -- a move longer than a trunk is wide -------------------------------------------

def test_a_move_across_a_trunk_does_not_step_over_it(clock):
    trunk = np.array([[0.0, 0.0, 0.0]], np.float32)
    radius = np.array([0.4], np.float32)
    host = camera_at(clock, level(), trunk, radius, at=(-1.5, 0.0, 0.03))
    host.collide_and_clamp()
    x, z = settled(host, 1.5, 0.03)
    assert x < 1.5 - 1e-3
    assert math.hypot(x, z) >= 0.4 + host.player_radius - 0.02


def test_a_move_through_the_axis_of_a_trunk_does_not_step_over_it(clock):
    trunk = np.array([[0.0, 0.0, 0.0]], np.float32)
    host = camera_at(clock, level(), trunk, np.array([0.4], np.float32), at=(-1.5, 0.0, 0.0))
    host.collide_and_clamp()
    x, _z = settled(host, 1.5, 0.0)
    assert x < 1.5 - 1e-3


# -- rocks that come and go ---------------------------------------------------------

def rock_at(x, z, radius):
    positions = np.array([[x, 0.0, z]], np.float32)
    return lambda px, pz, reach: (positions, np.array([radius], np.float32))


def host_with(clock, *sources, at=(0.0, 0.0, 0.0)):
    host = camera_at(clock, flat_field(height=0.0), at=at)
    for source in sources:
        host.add_collider_source(source)
    host.collide_and_clamp()
    run(host, clock, 0.1)
    return host


def test_a_camera_is_put_out_of_a_rock_a_source_supplies(clock):
    host = host_with(clock, rock_at(5.0, 5.0, 1.0), at=(5.5, 0.0, 5.0))
    x, z = settled(host, 5.2, 5.0)
    assert math.hypot(x - 5.0, z - 5.0) == pytest.approx(1.0 + host.player_radius, abs=0.03)
    assert settled(host, 9.0, 9.0) == pytest.approx((9.0, 9.0), abs=1e-6)


def test_a_move_through_a_rock_a_source_supplies_goes_around_it(clock):
    host = host_with(clock, rock_at(5.0, 0.0, 0.6), at=(3.0, 0.0, 0.1))
    host.collide_and_clamp()
    x, z = settled(host, 7.0, 0.1)
    assert math.hypot(x - 5.0, z) >= 0.6 + host.player_radius - 0.03


def test_fixed_and_streamed_colliders_both_count(clock):
    host = camera_at(clock, flat_field(height=0.0), np.array([[-5.0, 0.0, -5.0]], np.float32),
                     np.array([1.0], np.float32), at=(5.5, 0.0, 5.0))
    host.add_collider_source(rock_at(5.0, 5.0, 1.0))
    host.collide_and_clamp()
    run(host, clock, 0.1)
    near_rock = settled(host, 5.1, 5.0)
    assert math.hypot(near_rock[0] - 5.0, near_rock[1] - 5.0) >= 1.0 + host.player_radius - 0.03
    near_trunk = settled(host, -5.1, -5.0)
    assert math.hypot(near_trunk[0] + 5.0, near_trunk[1] + 5.0) >= 1.0 + host.player_radius - 0.03


def test_sources_are_kept_when_the_walker_is_bound_to_another_field(clock):
    host = host_with(clock, rock_at(5.0, 5.0, 1.0), at=(5.5, 0.0, 5.0))
    host.init_walk(flat_field(height=0.0))
    host.collide_and_clamp()
    run(host, clock, 0.1)
    x, z = settled(host, 5.2, 5.0)
    assert math.hypot(x - 5.0, z - 5.0) >= 1.0 + host.player_radius - 0.03


def test_a_source_that_is_removed_stops_stopping_the_camera(clock):
    host = camera_at(clock, flat_field(height=0.0), at=(5.5, 0.0, 5.0))
    handle = host.add_collider_source(rock_at(5.0, 5.0, 1.0))
    host.collide_and_clamp()
    run(host, clock, 0.1)
    handle.remove()
    assert settled(host, 5.1, 5.0) == pytest.approx((5.1, 5.0), abs=1e-6)
