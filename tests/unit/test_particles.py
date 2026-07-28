"""The particle pool and the emitter node: everything except the drawing.

A particle system is a simulation with a renderer bolted on, and the simulation
is numpy arrays.  So all of the interesting behaviour -- birth, motion, ageing,
death, compaction, budget -- is asserted about here with no GL context at all.
"""

import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import particles


def pool(capacity=16, **named):
    return particles.ParticlePool(capacity=capacity, **named)


class TestEmission:
    def test_a_new_pool_is_empty(self):
        assert pool().live == 0

    def test_emitting_makes_particles(self):
        p = pool()
        assert p.emit(5) == 5
        assert p.live == 5

    def test_emission_is_capped_by_the_capacity(self):
        p = pool(capacity=4)
        assert p.emit(10) == 4
        assert p.live == 4

    def test_a_full_pool_emits_nothing_more(self):
        p = pool(capacity=4)
        p.emit(4)
        assert p.emit(3) == 0

    def test_particles_start_where_they_were_emitted(self):
        p = pool()
        p.emit(3, position=(1.0, 2.0, 3.0))
        assert np.allclose(p.position[:3], (1.0, 2.0, 3.0))

    def test_particles_start_with_the_given_velocity(self):
        p = pool()
        p.emit(2, velocity=(0.0, 5.0, 0.0), spread=0.0, speed_variation=0.0)
        assert np.allclose(p.velocity[:2], (0.0, 5.0, 0.0))

    def test_spread_scatters_the_direction_without_changing_the_speed(self):
        p = pool(capacity=64, seed=1)
        p.emit(64, velocity=(0.0, 4.0, 0.0), spread=math.pi / 4,
               speed_variation=0.0)
        speeds = np.linalg.norm(p.velocity[:64], axis=1)
        assert np.allclose(speeds, 4.0, atol=1e-4)
        assert p.velocity[:64, 0].std() > 0.1

    def test_zero_spread_gives_a_perfectly_straight_jet(self):
        p = pool(capacity=32, seed=1)
        p.emit(32, velocity=(0.0, 4.0, 0.0), spread=0.0, speed_variation=0.0)
        assert p.velocity[:32, 0].std() == pytest.approx(0.0, abs=1e-6)

    def test_speed_variation_scatters_the_speed(self):
        p = pool(capacity=64, seed=2)
        p.emit(64, velocity=(0.0, 4.0, 0.0), spread=0.0, speed_variation=0.5)
        speeds = np.linalg.norm(p.velocity[:64], axis=1)
        assert speeds.std() > 0.1
        assert speeds.min() > 0.0

    def test_lifetime_variation_scatters_the_lifetime(self):
        p = pool(capacity=64, seed=3)
        p.emit(64, lifetime=2.0, lifetime_variation=0.5)
        assert p.lifetime[:64].std() > 0.1
        assert p.lifetime[:64].min() > 0.0

    def test_every_particle_gets_its_own_random_number(self):
        """One number per particle is what lets a shader vary them for free."""
        p = pool(capacity=32, seed=4)
        p.emit(32)
        assert len(set(p.random[:32].tolist())) > 20

    def test_particles_start_unaged(self):
        p = pool()
        p.emit(4)
        assert not p.age[:4].any()

    def test_a_lifetime_of_zero_is_refused_rather_than_dividing_by_zero(self):
        p = pool()
        p.emit(2, lifetime=0.0)
        assert (p.lifetime[:2] > 0.0).all()


class TestStepping:
    def test_particles_move_along_their_velocity(self):
        p = pool()
        p.emit(1, position=(0.0, 0.0, 0.0), velocity=(1.0, 0.0, 0.0),
               spread=0.0, speed_variation=0.0)
        p.step(0.5)
        assert np.allclose(p.position[0], (0.5, 0.0, 0.0))

    def test_gravity_bends_the_path(self):
        p = pool()
        p.emit(1, velocity=(0.0, 0.0, 0.0))
        p.step(1.0, gravity=(0.0, -10.0, 0.0))
        assert p.velocity[0][1] == pytest.approx(-10.0)
        assert p.position[0][1] < 0.0

    def test_drag_slows_particles_down(self):
        p = pool()
        p.emit(1, velocity=(10.0, 0.0, 0.0), spread=0.0, speed_variation=0.0)
        p.step(0.1, drag=5.0)
        assert 0.0 < p.velocity[0][0] < 10.0

    def test_drag_never_reverses_a_particle(self):
        """A large step with heavy drag must not push the particle backwards."""
        p = pool()
        p.emit(1, velocity=(10.0, 0.0, 0.0), spread=0.0, speed_variation=0.0)
        p.step(10.0, drag=50.0)
        assert p.velocity[0][0] >= 0.0

    def test_particles_age(self):
        p = pool()
        p.emit(1, lifetime=2.0, lifetime_variation=0.0)
        p.step(0.5)
        assert p.age[0] == pytest.approx(0.5)

    def test_particles_spin(self):
        """Starting angles are random, so it is the change that is asserted.

        Emitting every particle at rotation zero makes a cloud of sprites all
        pointing the same way, which reads as a grid rather than as smoke.
        """
        p = pool(seed=5)
        p.emit(1, spin=2.0, spin_variation=0.0)
        before = float(p.rotation[0])
        p.step(0.5)
        assert float(p.rotation[0]) - before == pytest.approx(1.0)

    def test_stepping_an_empty_pool_is_harmless(self):
        pool().step(0.1, gravity=(0.0, -9.8, 0.0))

    def test_a_zero_step_changes_nothing(self):
        p = pool()
        p.emit(1, velocity=(1.0, 0.0, 0.0), spread=0.0, speed_variation=0.0)
        before = p.position[0].copy()
        p.step(0.0)
        assert np.allclose(p.position[0], before)


class TestDeath:
    def test_a_particle_past_its_lifetime_is_gone(self):
        p = pool()
        p.emit(1, lifetime=1.0, lifetime_variation=0.0)
        p.step(1.5)
        assert p.live == 0

    def test_survivors_are_kept(self):
        p = pool()
        p.emit(1, lifetime=0.5, lifetime_variation=0.0)
        p.emit(1, lifetime=5.0, lifetime_variation=0.0)
        p.step(1.0)
        assert p.live == 1
        assert p.lifetime[0] == pytest.approx(5.0)

    def test_the_living_stay_packed_at_the_front(self):
        """A contiguous live prefix is what makes the GPU upload one slice."""
        p = pool(capacity=8)
        for index in range(6):
            p.emit(1, lifetime=1.0 + index, lifetime_variation=0.0,
                   position=(float(index), 0.0, 0.0))
        p.step(3.5)                                  # kills lifetimes 1, 2, 3
        assert p.live == 3
        assert sorted(p.position[:3, 0].tolist()) == [3.0, 4.0, 5.0]

    def test_dying_frees_room_for_new_particles(self):
        p = pool(capacity=2)
        p.emit(2, lifetime=1.0, lifetime_variation=0.0)
        p.step(2.0)
        assert p.emit(2) == 2

    def test_compaction_does_not_disturb_the_survivors_state(self):
        p = pool(capacity=4)
        p.emit(1, lifetime=0.1, lifetime_variation=0.0)
        p.emit(1, lifetime=9.0, lifetime_variation=0.0,
               velocity=(3.0, 0.0, 0.0), spread=0.0, speed_variation=0.0)
        p.step(0.5)
        assert p.live == 1
        assert p.velocity[0][0] == pytest.approx(3.0)


class TestLifeFraction:
    def test_a_new_particle_is_at_the_start_of_its_life(self):
        p = pool()
        p.emit(1, lifetime=2.0, lifetime_variation=0.0)
        assert p.life_fraction()[0] == pytest.approx(0.0)

    def test_half_way_through_reads_one_half(self):
        p = pool()
        p.emit(1, lifetime=2.0, lifetime_variation=0.0)
        p.step(1.0)
        assert p.life_fraction()[0] == pytest.approx(0.5)

    def test_the_fraction_covers_only_the_living(self):
        p = pool(capacity=8)
        p.emit(3)
        assert p.life_fraction().shape == (3,)


class TestInstanceData:
    """What the GPU is handed: one row per living particle."""

    def test_one_row_per_living_particle(self):
        p = pool(capacity=8)
        p.emit(5)
        assert p.instances().shape == (5, particles.INSTANCE_FLOATS)

    def test_an_empty_pool_yields_an_empty_array_rather_than_none(self):
        assert pool().instances().shape == (0, particles.INSTANCE_FLOATS)

    def test_the_rows_are_float32_and_contiguous(self):
        p = pool()
        p.emit(3)
        rows = p.instances()
        assert rows.dtype == np.float32
        assert rows.flags['C_CONTIGUOUS']

    def test_the_first_three_columns_are_the_position(self):
        p = pool()
        p.emit(1, position=(1.0, 2.0, 3.0))
        assert np.allclose(p.instances()[0, :3], (1.0, 2.0, 3.0))

    def test_the_life_fraction_travels_with_each_particle(self):
        p = pool()
        p.emit(1, lifetime=4.0, lifetime_variation=0.0)
        p.step(1.0)
        assert p.instances()[0, particles.INSTANCE_LIFE] == pytest.approx(0.25)

    def test_the_instance_buffer_is_reused_between_frames(self):
        """A pool that reallocated every frame would churn for no reason."""
        p = pool()
        p.emit(4)
        assert p.instances().base is p.instances().base


class TestBudget:
    def test_the_pool_reports_how_full_it_is(self):
        p = pool(capacity=10)
        p.emit(4)
        assert p.capacity == 10
        assert p.live == 4

    def test_clearing_kills_everything_at_once(self):
        p = pool()
        p.emit(8)
        p.clear()
        assert p.live == 0

    def test_a_pool_sizes_its_arrays_once(self):
        p = pool(capacity=100)
        assert p.position.shape == (100, 3)
        assert p.age.shape == (100,)

    def test_stepping_a_full_pool_allocates_little(self):
        import tracemalloc

        p = pool(capacity=2000, seed=9)
        p.emit(2000, lifetime=1000.0)
        p.step(0.016)
        tracemalloc.start()
        before = tracemalloc.take_snapshot()
        for _ in range(30):
            p.step(0.016, gravity=(0.0, -9.8, 0.0), drag=0.1)
        after = tracemalloc.take_snapshot()
        tracemalloc.stop()
        grew = sum(entry.size_diff for entry in after.compare_to(before, 'filename'))
        assert grew < 65536, 'stepping allocated %d bytes' % (grew,)


class TestReproducibility:
    def test_a_seeded_pool_repeats_itself(self):
        first, second = pool(capacity=32, seed=11), pool(capacity=32, seed=11)
        for each in (first, second):
            each.emit(32, velocity=(0, 3, 0), spread=0.5)
            each.step(0.1)
        assert np.allclose(first.position[:32], second.position[:32])

    def test_two_different_seeds_differ(self):
        first, second = pool(capacity=32, seed=1), pool(capacity=32, seed=2)
        for each in (first, second):
            each.emit(32, velocity=(0, 3, 0), spread=0.5)
        assert not np.allclose(first.velocity[:32], second.velocity[:32])


class TestEmitterNode:
    """The scenegraph node: a pool, a rate, and the shape of what comes out."""

    def test_it_starts_with_no_particles(self):
        assert particles.ParticleEmitter().pool.live == 0

    def test_a_continuous_emitter_fills_up_over_time(self):
        emitter = particles.ParticleEmitter(rate=100.0, maxParticles=64,
                                            lifetime=10.0)
        emitter.simulate(0.1)
        assert emitter.pool.live == 10

    def test_fractional_emission_accumulates_rather_than_being_lost(self):
        """At 10/s and 1/60 s a frame, a naive int() emits nothing, ever."""
        emitter = particles.ParticleEmitter(rate=10.0, maxParticles=64,
                                            lifetime=10.0)
        for _ in range(60):
            emitter.simulate(1.0 / 60.0)
        assert emitter.pool.live == pytest.approx(10, abs=1)

    def test_a_burst_emits_once_and_then_stops(self):
        emitter = particles.ParticleEmitter(rate=0.0, burst=20, maxParticles=64,
                                            lifetime=10.0)
        emitter.simulate(0.1)
        assert emitter.pool.live == 20
        emitter.simulate(0.1)
        assert emitter.pool.live == 20

    def test_a_burst_can_be_fired_again(self):
        emitter = particles.ParticleEmitter(rate=0.0, burst=5, maxParticles=64,
                                            lifetime=10.0)
        emitter.simulate(0.1)
        emitter.fire()
        emitter.simulate(0.1)
        assert emitter.pool.live == 10

    def test_a_disabled_emitter_emits_nothing(self):
        emitter = particles.ParticleEmitter(rate=100.0, enabled=False,
                                            maxParticles=64, lifetime=10.0)
        emitter.simulate(0.1)
        assert emitter.pool.live == 0

    def test_a_disabled_emitter_still_ages_what_is_already_out(self):
        """Switching an emitter off should let its smoke clear, not freeze it."""
        emitter = particles.ParticleEmitter(rate=100.0, maxParticles=64,
                                            lifetime=1.0, lifetimeVariation=0.0)
        emitter.simulate(0.1)
        emitter.enabled = False
        for _ in range(20):
            emitter.simulate(0.1)
        assert emitter.pool.live == 0

    def test_gravity_and_drag_reach_the_pool(self):
        emitter = particles.ParticleEmitter(
            rate=0.0, burst=1, maxParticles=4, lifetime=10.0,
            gravity=(0.0, -10.0, 0.0), speed=0.0, spread=0.0)
        for _ in range(10):
            emitter.simulate(0.1)
        assert emitter.pool.velocity[0][1] < -5.0

    def test_the_pool_is_sized_by_max_particles(self):
        assert particles.ParticleEmitter(maxParticles=250).pool.capacity == 250

    def test_changing_max_particles_resizes_the_pool(self):
        emitter = particles.ParticleEmitter(maxParticles=8)
        emitter.maxParticles = 32
        emitter.simulate(0.0)
        assert emitter.pool.capacity == 32

    def test_a_long_frame_is_clamped_so_a_hitch_does_not_teleport_everything(self):
        """A window drag or a stalled upload gives a frame of seconds.

        Integrating it honestly throws every particle out of sight; losing the
        time is the lesser artefact, and it is the same clamp a fixed-timestep
        physics loop applies for the same reason.
        """
        emitter = particles.ParticleEmitter(
            rate=0.0, burst=1, maxParticles=4, lifetime=1000.0,
            speed=10.0, speedVariation=0.0, spread=0.0,
            direction=(1.0, 0.0, 0.0), gravity=(0.0, 0.0, 0.0))
        emitter.simulate(60.0)
        assert emitter.pool.position[0][0] == pytest.approx(
            10.0 * particles.MAX_STEP)

    def test_a_negative_step_is_ignored(self):
        emitter = particles.ParticleEmitter(rate=10.0, maxParticles=64)
        emitter.simulate(-1.0)
        assert emitter.pool.live == 0

    def test_the_emitter_reports_its_load_for_a_debug_overlay(self):
        emitter = particles.ParticleEmitter(rate=100.0, maxParticles=64,
                                            lifetime=10.0)
        emitter.simulate(0.2)
        assert emitter.particleCount == emitter.pool.live


class TestWorldSpace:
    """Whether particles follow the emitter once they have left it."""

    def test_world_space_particles_are_emitted_where_the_emitter_was(self):
        emitter = particles.ParticleEmitter(rate=0.0, burst=1, maxParticles=4,
                                            worldSpace=True, speed=0.0, spread=0.0)
        emitter.simulate(0.0, origin=(5.0, 0.0, 0.0))
        assert np.allclose(emitter.pool.position[0], (5.0, 0.0, 0.0))

    def test_local_space_particles_are_emitted_at_the_origin(self):
        emitter = particles.ParticleEmitter(rate=0.0, burst=1, maxParticles=4,
                                            worldSpace=False, speed=0.0, spread=0.0)
        emitter.simulate(0.0, origin=(5.0, 0.0, 0.0))
        assert np.allclose(emitter.pool.position[0], (0.0, 0.0, 0.0))


class TestLifeCurves:
    """Size and colour over a particle's life belong to the emitter, not to it."""

    def test_size_is_interpolated_between_the_two_ends(self):
        emitter = particles.ParticleEmitter(size=2.0, endSize=0.0)
        assert emitter.sizeAt(0.0) == pytest.approx(2.0)
        assert emitter.sizeAt(1.0) == pytest.approx(0.0)
        assert emitter.sizeAt(0.5) == pytest.approx(1.0)

    def test_colour_is_interpolated_between_the_two_ends(self):
        emitter = particles.ParticleEmitter(color=(1.0, 0.0, 0.0),
                                            endColor=(0.0, 0.0, 1.0))
        assert np.allclose(emitter.colorAt(0.5), (0.5, 0.0, 0.5))

    def test_alpha_is_interpolated_between_the_two_ends(self):
        emitter = particles.ParticleEmitter(alpha=1.0, endAlpha=0.0)
        assert emitter.alphaAt(0.25) == pytest.approx(0.75)

    def test_the_curves_are_what_the_shader_is_told(self):
        """A uniform pair, not a texture: the curve is two ends and a lerp."""
        emitter = particles.ParticleEmitter(size=3.0, endSize=1.0,
                                            color=(1.0, 0.5, 0.0),
                                            endColor=(0.0, 0.0, 0.0),
                                            alpha=0.9, endAlpha=0.1)
        uniforms = emitter.lifeUniforms()
        assert uniforms['sizeRange'] == pytest.approx((3.0, 1.0))
        assert np.allclose(uniforms['startColor'], (1.0, 0.5, 0.0, 0.9))
        assert np.allclose(uniforms['endColor'], (0.0, 0.0, 0.0, 0.1))


class TestBlending:
    def test_additive_is_the_default_because_most_effects_glow(self):
        assert particles.ParticleEmitter().blending == 'additive'

    def test_alpha_blending_can_be_chosen_for_smoke(self):
        assert particles.ParticleEmitter(blending='alpha').blending == 'alpha'

    def test_an_unknown_blend_falls_back_rather_than_raising(self):
        emitter = particles.ParticleEmitter(blending='nonsense')
        assert emitter.blendMode() == particles.BLEND_MODES['additive']


class TestPresets:
    """Named starting points, so an effect is one line rather than twenty."""

    def test_every_preset_builds_an_emitter(self):
        for name in particles.PRESETS:
            assert isinstance(particles.preset(name), particles.ParticleEmitter)

    def test_a_preset_can_be_overridden(self):
        assert particles.preset('smoke', maxParticles=7).maxParticles == 7

    def test_an_unknown_preset_is_an_error_rather_than_a_silent_default(self):
        with pytest.raises(KeyError):
            particles.preset('nonexistent')

    def test_the_explosion_preset_is_a_burst_rather_than_continuous(self):
        explosion = particles.preset('explosion')
        assert explosion.burst > 0
        assert explosion.rate == 0.0

    def test_the_smoke_preset_rises_and_fades(self):
        smoke = particles.preset('smoke')
        assert smoke.gravity[1] > 0.0
        assert smoke.endAlpha < smoke.alpha


class TestSizeIsAMultiplier:
    """A particle stores how it differs from its emitter, not its own size."""

    def test_particles_are_born_with_a_unit_mean_size_factor(self):
        emitter = particles.ParticleEmitter(rate=0.0, burst=64, maxParticles=64,
                                            size=5.0, sizeVariation=0.0,
                                            lifetime=10.0)
        emitter.simulate(0.0)
        assert np.allclose(emitter.pool.size[:64], 1.0)

    def test_size_variation_scatters_the_factor(self):
        emitter = particles.ParticleEmitter(rate=0.0, burst=64, maxParticles=64,
                                            size=5.0, sizeVariation=0.5,
                                            lifetime=10.0, seed=3)
        emitter.simulate(0.0)
        factors = emitter.pool.size[:64]
        assert factors.std() > 0.05
        assert abs(float(factors.mean()) - 1.0) < 0.15

    def test_resizing_an_emitter_resizes_what_is_already_in_the_air(self):
        """The absolute size is a uniform, so it is not baked into a particle."""
        emitter = particles.ParticleEmitter(rate=0.0, burst=4, maxParticles=8,
                                            size=1.0, sizeVariation=0.0,
                                            lifetime=10.0)
        emitter.simulate(0.0)
        emitter.size = 4.0
        assert emitter.lifeUniforms()['sizeRange'][0] == pytest.approx(4.0)
        assert np.allclose(emitter.pool.size[:4], 1.0)
