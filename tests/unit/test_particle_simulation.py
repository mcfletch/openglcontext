"""Where particles start, what moves them and how they look over a life; no GL.

The engine's particle simulation (:mod:`OpenGLContext.scenegraph.particlesim`)
beyond the pool itself: the emission sources (a point, a cone, a sphere, a
polyline, a surface, a volume), the physics models applied in order each step
(a constant force, wind, a bounding mesh), the colour and texture-frame ramps,
and the clock a system steps by.
"""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import particlesim
from OpenGLContext.scenegraph.particlesim import (
    Bounds, ColorRamp, ConeSource, ConstantForce, Emission, FrameRamp, ParticlePool,
    PointSource, PolylineSource, SphereSource, StepClock, SurfaceSource, VolumeSource,
    Wind, launch,
)


def rng(seed=3):
    return np.random.default_rng(seed)


def cube(half=1.0):
    """The twelve triangles of a cube of side 2*half about the origin, outward wound"""
    h = half
    corners = np.array([(-h, -h, -h), (h, -h, -h), (h, h, -h), (-h, h, -h),
                        (-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h)], 'f')
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (0, 4, 7, 3)]
    triangles = []
    for a, b, c, d in faces:
        triangles.append(corners[[a, b, c]])
        triangles.append(corners[[a, c, d]])
    return np.array(triangles, 'f')


class TestSources:
    def test_a_point_source_starts_every_particle_at_its_position(self):
        positions, directions = PointSource((1, 2, 3), (0, 0, 2)).sample(rng(), 5)
        assert np.allclose(positions, (1, 2, 3))
        assert np.allclose(directions, (0, 0, 1))

    def test_a_point_source_without_a_direction_throws_every_way(self):
        _positions, directions = PointSource((0, 0, 0), (0, 0, 0)).sample(rng(), 400)
        assert np.allclose(np.linalg.norm(directions, axis=1), 1.0)
        assert np.all(np.abs(directions.mean(axis=0)) < 0.15)

    def test_a_cone_keeps_inside_its_angle(self):
        _positions, directions = ConeSource((0, 0, 0), (0, 1, 0), 0.3).sample(rng(), 500)
        angles = np.arccos(np.clip(directions[:, 1], -1, 1))
        assert angles.max() <= 0.3 + 1e-5
        assert angles.max() > 0.25

    def test_a_cone_of_no_angle_is_a_jet(self):
        _positions, directions = ConeSource((0, 0, 0), (1, 0, 0), 0.0).sample(rng(), 20)
        assert np.allclose(directions, (1, 0, 0))

    def test_a_sphere_source_throws_every_way_from_one_point(self):
        positions, directions = SphereSource((0, 1, 0)).sample(rng(), 600)
        assert np.allclose(positions, (0, 1, 0))
        assert np.allclose(np.linalg.norm(directions, axis=1), 1.0)
        assert (directions[:, 1] < -0.5).any() and (directions[:, 1] > 0.5).any()

    def test_a_polyline_source_starts_particles_on_its_segments_by_length(self):
        points = np.array([(0, 0, 0), (1, 0, 0), (1, 3, 0)], 'f')
        source = PolylineSource(points, [(0, 1), (1, 2)], (0, 1, 0))
        positions, directions = source.sample(rng(), 2000)
        on_first = np.isclose(positions[:, 1], 0) & (positions[:, 0] <= 1)
        on_second = np.isclose(positions[:, 0], 1) & (positions[:, 1] <= 3)
        assert np.all(on_first | on_second)
        # The second segment is three times as long, so it holds about 3/4.
        assert 0.7 < np.count_nonzero(positions[:, 1] > 1e-6) / 2000 < 0.8
        assert np.allclose(directions, (0, 1, 0))

    def test_a_polyline_with_no_segments_emits_nowhere(self):
        source = PolylineSource(np.zeros((0, 3), 'f'), np.zeros((0, 2), int), (0, 1, 0))
        assert source.empty
        positions, _directions = source.sample(rng(), 4)
        assert positions.shape == (0, 3)

    def test_a_surface_source_starts_particles_on_the_surface_along_its_normal(self):
        source = SurfaceSource(cube())
        positions, directions = source.sample(rng(), 600)
        assert np.allclose(np.abs(positions).max(axis=1), 1.0, atol=1e-5)
        # Outward: the direction points away from the centre, on the face's axis.
        assert np.all(np.einsum('ij,ij->i', positions, directions) > 0.99)

    def test_a_two_sided_surface_throws_from_both_faces(self):
        quad = np.array([[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         [(0, 0, 0), (1, 1, 0), (0, 1, 0)]], 'f')
        _positions, directions = SurfaceSource(quad, two_sided=True).sample(rng(), 400)
        assert (directions[:, 2] > 0.99).any() and (directions[:, 2] < -0.99).any()

    def test_a_surface_source_weights_its_triangles_by_area(self):
        small = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        large = [(10, 0, 0), (13, 0, 0), (10, 3, 0)]
        positions, _directions = SurfaceSource(np.array([small, large], 'f')).sample(rng(), 3000)
        assert 0.85 < np.count_nonzero(positions[:, 0] >= 10) / 3000 < 0.95

    def test_a_volume_source_starts_particles_inside_its_volume(self):
        source = VolumeSource(cube(), (0, 1, 0))
        positions, directions = source.sample(rng(), 500)
        assert len(positions) == 500
        assert np.all(np.abs(positions) <= 1.0)
        assert (np.abs(positions).max(axis=1) < 0.9).mean() > 0.5
        assert np.allclose(directions, (0, 1, 0))

    def test_a_volume_source_follows_a_shape_that_is_not_its_box(self):
        # A wedge filling half of its bounding box.
        wedge = np.array([
            [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 1), (0, 1, 1), (1, 0, 1)],
            [(0, 0, 0), (0, 0, 1), (1, 0, 1)], [(0, 0, 0), (1, 0, 1), (1, 0, 0)],
            [(0, 0, 0), (0, 1, 0), (0, 1, 1)], [(0, 0, 0), (0, 1, 1), (0, 0, 1)],
            [(1, 0, 0), (1, 0, 1), (0, 1, 1)], [(1, 0, 0), (0, 1, 1), (0, 1, 0)],
        ], 'f')
        positions, _directions = VolumeSource(wedge, (0, 1, 0)).sample(rng(), 400)
        assert np.all(positions[:, 0] + positions[:, 1] <= 1.0 + 1e-5)

    def test_a_volume_that_is_not_internal_emits_from_its_boundary(self):
        positions, _directions = VolumeSource(cube(), (0, 1, 0), internal=False).sample(rng(), 200)
        assert np.allclose(np.abs(positions).max(axis=1), 1.0, atol=1e-5)

    def test_launch_gives_each_particle_a_speed_within_the_variation(self):
        positions, velocities = launch(PointSource((0, 0, 0), (0, 1, 0)), rng(), 500,
                                       speed=2.0, variation=0.25)
        speeds = np.linalg.norm(velocities, axis=1)
        assert speeds.min() >= 1.5 - 1e-5 and speeds.max() <= 2.5 + 1e-5
        assert speeds.std() > 0.1

    def test_launch_never_gives_a_negative_speed(self):
        _positions, velocities = launch(PointSource((0, 0, 0), (0, 1, 0)), rng(), 200,
                                        speed=1.0, variation=3.0)
        assert np.all(velocities[:, 1] >= 0.0)


class TestSpawning:
    def test_spawn_takes_a_position_and_velocity_per_particle(self):
        pool = ParticlePool(8, seed=1)
        made = pool.spawn([(0, 0, 0), (1, 1, 1)], [(1, 0, 0), (0, 1, 0)], lifetime=2.0)
        assert made == 2
        assert np.allclose(pool.position[:2], [(0, 0, 0), (1, 1, 1)])
        assert np.allclose(pool.velocity[:2], [(1, 0, 0), (0, 1, 0)])

    def test_spawn_is_held_to_the_capacity(self):
        pool = ParticlePool(3, seed=1)
        assert pool.spawn(np.zeros((5, 3)), np.zeros((5, 3))) == 3

    def test_unturned_particles_start_with_no_rotation(self):
        pool = ParticlePool(8, seed=1)
        pool.spawn(np.zeros((8, 3)), np.zeros((8, 3)), turned=False)
        assert not pool.rotation[:8].any()

    def test_a_resized_pool_keeps_the_survivors_that_fit(self):
        pool = ParticlePool(8, seed=1)
        pool.spawn([(index, 0, 0) for index in range(6)], np.zeros((6, 3)), lifetime=3.0)
        smaller = pool.resized(4)
        assert smaller.capacity == 4 and smaller.live == 4
        assert np.allclose(smaller.position[:4, 0], [0, 1, 2, 3])
        assert np.allclose(smaller.lifetime[:4], 3.0)
        larger = pool.resized(20)
        assert larger.capacity == 20 and larger.live == 6
        assert larger.rng is pool.rng

    def test_the_age_in_seconds_is_kept(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn(np.zeros((1, 3)), np.zeros((1, 3)), lifetime=4.0)
        pool.step(0.05)
        pool.step(0.05)
        assert pool.age[0] == pytest.approx(0.1)


class TestModels:
    def test_models_are_applied_in_the_order_given(self):
        calls = []

        class Recording(particlesim.ParticleModel):
            def __init__(self, name):
                self.name = name

            def accelerate(self, velocity, dt, rng):
                calls.append(self.name)

        pool = ParticlePool(4, seed=1)
        pool.spawn(np.zeros((1, 3)), np.zeros((1, 3)))
        pool.step(0.1, models=[Recording('a'), Recording('b'), Recording('c')])
        assert calls == ['a', 'b', 'c']

    def test_a_force_accelerates_by_force_over_mass(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn(np.zeros((1, 3)), np.zeros((1, 3)))
        pool.step(0.1, models=[ConstantForce((0, -10, 0), mass=2.0)])
        assert pool.velocity[0] == pytest.approx((0, -0.5, 0))

    def test_a_force_on_a_massless_particle_is_an_acceleration(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn(np.zeros((1, 3)), np.zeros((1, 3)))
        pool.step(0.1, models=[ConstantForce((0, -9.8, 0), mass=0.0)])
        assert pool.velocity[0] == pytest.approx((0, -0.98, 0))

    def test_wind_pushes_by_its_pressure_on_the_surface_area(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn(np.zeros((2, 3)), np.zeros((2, 3)))
        wind = Wind((1, 0, 0), speed=10.0, gustiness=0.0, turbulence=0.0, area=0.5, mass=1.0)
        pool.step(0.1, models=[wind])
        expected = 10.0 ** 2 * particlesim.WIND_PRESSURE * 0.5 * 0.1
        assert np.allclose(pool.velocity[:2], (expected, 0, 0), rtol=1e-5)

    def test_gusts_vary_the_wind_from_step_to_step(self):
        wind = Wind((1, 0, 0), speed=10.0, gustiness=0.5, turbulence=0.0, area=1.0, mass=1.0)
        pushes = []
        for _ in range(10):
            velocity = np.zeros((1, 3), 'f')
            wind.accelerate(velocity, 0.1, rng(len(pushes)))
            pushes.append(velocity[0, 0])
        assert np.std(pushes) > 0.0
        low = 5.0 ** 2 * particlesim.WIND_PRESSURE * 0.1
        high = 15.0 ** 2 * particlesim.WIND_PRESSURE * 0.1
        assert low - 1e-5 <= min(pushes) and max(pushes) <= high + 1e-5

    def test_turbulence_scatters_the_wind_off_its_direction(self):
        wind = Wind((1, 0, 0), speed=10.0, gustiness=0.0, turbulence=0.5, area=1.0, mass=1.0)
        velocity = np.zeros((300, 3), 'f')
        wind.accelerate(velocity, 0.1, rng())
        magnitudes = np.linalg.norm(velocity, axis=1)
        assert np.allclose(magnitudes, magnitudes[0], rtol=1e-4)
        cosines = velocity[:, 0] / magnitudes
        assert cosines.min() >= math.cos(math.pi * 0.5) - 1e-5
        assert cosines.std() > 0.05

    def test_a_wind_without_speed_does_nothing(self):
        velocity = np.zeros((3, 3), 'f')
        Wind((1, 0, 0), speed=0.0, gustiness=0.5, turbulence=0.5, area=1.0,
             mass=1.0).accelerate(velocity, 0.1, rng())
        assert not velocity.any()

    def test_a_bounding_mesh_turns_a_particle_back(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn([(0, 0, 0.9)], [(0, 0, 2.0)])
        pool.step(0.1, models=[Bounds(cube())])
        assert pool.velocity[0] == pytest.approx((0, 0, -2.0))
        assert pool.position[0, 2] < 1.0

    def test_a_bounding_mesh_keeps_particles_in_whatever_the_steps(self):
        pool = ParticlePool(400, seed=4)
        positions, velocities = launch(SphereSource((0, 0, 0)), rng(), 400, speed=3.0,
                                       variation=0.5)
        pool.spawn(positions, velocities, lifetime=100.0)
        bounds = Bounds(cube())
        for _ in range(60):
            pool.step(0.05, models=[bounds])
        assert np.all(np.abs(pool.position[:pool.live]) <= 1.0 + 1e-3)

    def test_a_bounding_mesh_holds_particles_that_start_outside_it_out(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn([(0, 0, 1.1)], [(0, 0, -2.0)])
        pool.step(0.1, models=[Bounds(cube())])
        assert pool.position[0, 2] > 1.0

    def test_a_particle_that_misses_the_mesh_is_left_alone(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn([(5, 5, 5)], [(1, 0, 0)])
        pool.step(0.1, models=[Bounds(cube())])
        assert pool.position[0] == pytest.approx((5.1, 5, 5))

    def test_an_empty_bounding_mesh_bounds_nothing(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn([(0, 0, 0)], [(10, 0, 0)])
        pool.step(0.1, models=[Bounds(np.zeros((0, 3, 3), 'f'))])
        assert pool.position[0] == pytest.approx((1, 0, 0))


class TestRamps:
    def test_a_colour_ramp_interpolates_between_its_keys(self):
        ramp = ColorRamp([0.0, 1.0], [(1, 0, 0, 1), (0, 0, 1, 0)])
        assert np.allclose(ramp.at(np.array([0.5])), [(0.5, 0, 0.5, 0.5)])

    def test_a_colour_ramp_holds_its_ends(self):
        ramp = ColorRamp([1.0, 2.0], [(1, 0, 0, 1), (0, 1, 0, 1)])
        assert np.allclose(ramp.at(np.array([0.0, 5.0])), [(1, 0, 0, 1), (0, 1, 0, 1)])

    def test_colours_without_alpha_are_opaque(self):
        ramp = ColorRamp([0.0], [(0.2, 0.4, 0.6)])
        assert np.allclose(ramp.at(np.array([3.0])), [(0.2, 0.4, 0.6, 1.0)])

    def test_unsorted_keys_are_put_in_order_with_their_colours(self):
        ramp = ColorRamp([1.0, 0.0], [(0, 0, 1, 1), (1, 0, 0, 1)])
        assert np.allclose(ramp.at(np.array([0.0])), [(1, 0, 0, 1)])

    def test_a_ramp_uses_only_the_keys_it_has_colours_for(self):
        ramp = ColorRamp([0.0, 1.0, 2.0], [(1, 0, 0, 1), (0, 1, 0, 1)])
        assert len(ramp) == 2

    def test_a_ramp_of_nothing_is_empty(self):
        assert not ColorRamp([], [])
        assert ColorRamp([], []).translucent is False

    def test_a_ramp_says_whether_any_colour_is_translucent(self):
        assert ColorRamp([0, 1], [(1, 1, 1, 1), (1, 1, 1, 0.5)]).translucent
        assert not ColorRamp([0, 1], [(1, 1, 1), (1, 0, 1)]).translucent

    def test_a_frame_ramp_steps_rather_than_blending(self):
        frames = np.arange(3 * 4 * 2, dtype='f').reshape(3, 4, 2)
        ramp = FrameRamp([0.0, 1.0, 2.0], frames)
        assert list(ramp.index(np.array([0.0, 0.9, 1.0, 1.5, 7.0, -1.0]))) == [0, 0, 1, 1, 2, 0]

    def test_a_frame_ramp_of_nothing_is_empty(self):
        assert not FrameRamp([], np.zeros((0, 4, 2)))


class TestInstances:
    def test_colours_and_frames_go_with_each_particle(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn(np.zeros((2, 3)), [(1, 0, 0), (0, 2, 0)])
        rows = pool.instances(colors=np.array([(1, 0, 0, 1), (0, 1, 0, 0.5)], 'f'),
                              frames=np.array([0, 3]))
        assert np.allclose(rows[:, particlesim.INSTANCE_COLOR:particlesim.INSTANCE_COLOR + 4],
                           [(1, 0, 0, 1), (0, 1, 0, 0.5)])
        assert list(rows[:, particlesim.INSTANCE_FRAME]) == [0, 3]
        assert np.allclose(rows[:, particlesim.INSTANCE_VELOCITY:particlesim.INSTANCE_VELOCITY + 3],
                           [(1, 0, 0), (0, 2, 0)])

    def test_without_a_ramp_the_colour_is_white(self):
        pool = ParticlePool(4, seed=1)
        pool.spawn(np.zeros((1, 3)), np.zeros((1, 3)))
        rows = pool.instances()
        assert np.allclose(rows[0, particlesim.INSTANCE_COLOR:particlesim.INSTANCE_COLOR + 4], 1.0)


class TestEmission:
    def test_a_rate_accumulates_fractions(self):
        emission = Emission(rate=10.0)
        counts = [emission.due(0.016) for _ in range(100)]
        assert sum(counts) == 16

    def test_a_burst_is_released_once(self):
        emission = Emission(rate=0.0)
        emission.burst(30)
        assert emission.due(0.01) == 30
        assert emission.due(0.01) == 0

    def test_a_negative_rate_emits_nothing(self):
        assert Emission(rate=-5.0).due(1.0) == 0

    def test_dropping_what_is_owed_forgets_it(self):
        emission = Emission(rate=0.0)
        emission.burst(5)
        emission.drop()
        assert emission.due(0.1) == 0


class TestStepClock:
    def test_the_first_reading_steps_nothing(self):
        assert StepClock().step(10.0) == 0.0

    def test_it_steps_by_the_time_since_the_last_reading(self):
        clock = StepClock()
        clock.step(1.0)
        assert clock.step(1.05) == pytest.approx(0.05)

    def test_a_long_gap_is_clamped(self):
        clock = StepClock()
        clock.step(1.0)
        assert clock.step(9.0) == particlesim.MAX_STEP

    def test_time_running_backwards_steps_nothing(self):
        clock = StepClock()
        clock.step(5.0)
        assert clock.step(4.0) == 0.0

    def test_a_reset_clock_starts_again(self):
        clock = StepClock()
        clock.step(1.0)
        clock.reset()
        assert clock.step(3.0) == 0.0
