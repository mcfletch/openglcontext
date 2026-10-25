"""A landscape as bodies in the physics world: the ground, the trunks and the rocks near a focus.

The ground is the height field the renderer draws, so a body dropped on it comes to
rest where the player would stand. The trunks stand on that ground, one cylinder
shape for each radius class. The rocks are made as a focus nears them and dropped
as it leaves.
"""
import threading
import time

import numpy as np
import pytest

from OpenGLContext.physics.landscape import (
    Landscape, NearbyColliders, SampledGround, dome_proxy, ground_figures,
)
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.terrain import HeightField

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def flat_field(height=5.0, extent=200.0):
    return HeightField(np.ones((8, 8)), extent, height)


def ramp_field(extent=200.0, relief=20.0):
    """Ground rising along +x, so down the slope is toward -x."""
    grid = np.linspace(0.0, 1.0, 65)[None, :] * np.ones((65, 1))
    return HeightField(grid, extent, relief)


def ball(radius=0.3, at=(0, 3, 0)):
    return surfaces.shape(surfaces.sphere(radius), LOOK, translation=at)


@pytest.fixture
def physics():
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0))
    yield service
    service.close()


def run_for(service, seconds, frame=0.02):
    for _ in range(int(round(seconds / frame))):
        service.frame(frame)


# -- what a ground says about itself ------------------------------------------

class TestGroundFigures:
    def test_a_height_field_is_a_square_about_the_origin(self):
        extent, _, _ = ground_figures(ramp_field(extent=200.0))
        assert extent == ((-100.0, -100.0), (100.0, 100.0))

    def test_the_heights_reach_from_the_lowest_sample_to_the_highest(self):
        field = HeightField(np.array([[0.2, 0.9], [0.4, 0.5]]), 100.0, 50.0, base=10.0)
        _, (low, high), _ = ground_figures(field)
        assert low <= 10.0 + 0.2 * 50.0
        assert high >= 10.0 + 0.9 * 50.0
        assert high - low < 50.0

    def test_rock_standing_on_a_field_raises_its_ceiling(self):
        from OpenGLContext.scenegraph.rockground import RockyGround
        from OpenGLContext.scenegraph.terrain.relief import RockRelief

        field = ramp_field()
        rock = RockRelief(where=lambda x, z: np.ones(np.shape(x)), height=0.8)
        plain = ground_figures(field)[1][1]
        assert ground_figures(RockyGround(field, rock))[1][1] >= plain + 0.8

    def test_the_feature_is_one_cell_of_the_grid(self):
        _, _, feature = ground_figures(ramp_field(extent=200.0))
        assert feature == pytest.approx(200.0 / 64)

    def test_a_ground_that_is_only_a_function_is_sampled_for_its_heights(self):
        class Hill:
            def sample(self, x, z):
                return 3.0 * np.exp(-(np.asarray(x) ** 2 + np.asarray(z) ** 2) / 400.0)

        extent, (low, high), _ = ground_figures(Hill(), extent=((-50, -50), (50, 50)))
        assert extent == ((-50, -50), (50, 50))
        assert low <= 0.0 and high >= 3.0


# -- the ground and the trunks as bodies --------------------------------------

class TestALandscapeInTheWorld:
    def test_a_ball_dropped_on_the_ground_comes_to_rest_on_it(self, physics):
        field = flat_field(height=5.0)
        Landscape(physics, field)
        node = ball(0.3, at=(10.0, 9.0, -7.0))
        physics.add_dynamic(node, proxy='sphere', restitution=0.0, friction=0.9)
        run_for(physics, 3.0)
        assert node.translation[1] == pytest.approx(5.0 + 0.3, abs=0.03)

    def test_a_ball_rests_on_the_slope_it_is_dropped_on(self, physics):
        field = ramp_field()
        Landscape(physics, field)
        node = ball(0.3, at=(0.0, 14.0, 0.0))
        physics.add_dynamic(node, proxy='sphere', restitution=0.0, friction=0.9)
        run_for(physics, 4.0)
        x, y, z = node.translation
        slope = 20.0 / 200.0
        along = (y - field.height_at(x, z)) / np.sqrt(1.0 + slope * slope)
        assert along == pytest.approx(0.3, abs=0.05)

    def test_a_ball_rolling_down_the_slope_strikes_a_trunk(self, physics):
        field = ramp_field()
        trunk = np.array([[-3.0, 0.0, 0.0]])
        Landscape(physics, field, trunk, np.array([0.5]))
        node = ball(0.3, at=(0.0, field.height_at(0.0, 0.0) + 0.3, 0.0))
        physics.add_dynamic(node, proxy='sphere', restitution=0.0, friction=0.2)
        run_for(physics, 6.0)
        x = node.translation[0]
        assert x == pytest.approx(-3.0 + 0.5 + 0.3, abs=0.1)

    def test_a_ball_rolling_down_the_slope_goes_on_where_there_is_no_trunk(self, physics):
        field = ramp_field()
        Landscape(physics, field, np.array([[-3.0, 0.0, 6.0]]), np.array([0.5]))
        node = ball(0.3, at=(0.0, field.height_at(0.0, 0.0) + 0.3, 0.0))
        physics.add_dynamic(node, proxy='sphere', restitution=0.0, friction=0.2)
        run_for(physics, 6.0)
        assert node.translation[0] < -4.0

    def test_a_trunk_stands_on_the_ground_whatever_height_its_position_names(self, physics):
        field = flat_field(height=5.0)
        landscape = Landscape(physics, field, np.array([[4.0, -100.0, 4.0]]), np.array([0.4]),
                              trunk_height=10.0, trunk_sink=1.0)
        top = physics.raycast((4.0, 50.0, 4.0), (0.0, -1.0, 0.0))
        assert top.point[1] == pytest.approx(5.0 - 1.0 + 10.0, abs=0.02)
        assert landscape.trunk_count == 1

    def test_trunks_of_alike_radius_share_a_shape(self, physics):
        radii = np.array([0.31, 0.33, 0.34, 0.52])
        positions = np.array([[x * 5.0, 0.0, 0.0] for x in range(4)])
        landscape = Landscape(physics, flat_field(), positions, radii)
        assert len(landscape.trunks) == 2
        assert landscape.trunk_count == 4

    def test_a_trunk_is_never_thinner_than_its_radius(self, physics):
        Landscape(physics, flat_field(), np.array([[0.0, 0.0, 0.0]]), np.array([0.41]))
        assert physics.raycast((-5.0, 6.0, 0.0), (1.0, 0.0, 0.0)).point[0] \
            <= -0.41 + 1e-6

    def test_trunks_with_no_radius_are_posts(self, physics):
        landscape = Landscape(physics, flat_field(), np.array([[0.0, 0.0, 0.0]]))
        assert landscape.trunk_count == 1

    def test_removing_the_landscape_takes_the_ground_and_the_trunks_out(self, physics):
        landscape = Landscape(physics, flat_field(), np.array([[4.0, 0.0, 4.0]]),
                              np.array([0.4]))
        landscape.remove()
        landscape.remove()
        physics.frame(0.02)
        assert physics.raycast((4.0, 50.0, 4.0), (0.0, -1.0, 0.0)) is None

    def test_a_landscape_that_follows_a_focus_makes_the_tiles_ahead_of_it(self, physics):
        ground = CountingGround()
        landscape = Landscape(physics, ground)
        focus = [10.0, 0.0, 10.0]
        landscape.follow(lambda: tuple(focus))
        physics.frame(0.02)
        assert landscape.surface.wait(10.0)
        assert landscape.surface.tile_count == 9
        focus[0] = 100.0
        physics.frame(0.02)
        assert landscape.surface.wait(10.0)
        assert landscape.surface.tile_count > 9
        landscape.remove()

    def test_a_landscape_that_follows_a_focus_asks_again_only_in_another_tile(self, physics):
        ground = CountingGround()
        landscape = Landscape(physics, ground)
        focus = [10.0, 0.0, 10.0]
        landscape.follow(lambda: tuple(focus))
        physics.frame(0.02)
        landscape.surface.wait(10.0)
        calls = ground.calls
        focus[0] = 12.0
        physics.frame(0.02)
        landscape.surface.wait(10.0)
        assert ground.calls == calls
        landscape.remove()

    def test_a_landscape_with_nothing_to_stand_on_it_is_only_the_ground(self, physics):
        landscape = Landscape(physics, flat_field())
        assert landscape.trunk_count == 0 and landscape.trunks == []


# -- the ground, answered from tiles of its own samples ------------------------

class CountingGround:
    """A ground that counts the calls made of it and the points they asked about."""

    def __init__(self):
        self.calls = 0
        self.points = 0

    def sample(self, x, z):
        self.calls += 1
        self.points += np.size(x)
        x, z = np.asarray(x, dtype='d'), np.asarray(z, dtype='d')
        return 2.0 * np.sin(x / 10.0) + np.cos(z / 7.0)


class TestSampledGround:
    def test_it_answers_what_the_ground_answers(self):
        ground = CountingGround()
        cached = SampledGround(ground, spacing=0.5)
        rng = np.random.default_rng(2)
        x, z = rng.uniform(-200, 200, 500), rng.uniform(-200, 200, 500)
        assert cached.sample(x, z) == pytest.approx(ground.sample(x, z), abs=2e-3)

    def test_the_ground_of_a_landscape_is_given_the_normals_of_the_tiles(self, physics):
        landscape = Landscape(physics, CountingGround())
        assert landscape.body.proxy.shape.surface._normal is not None  # noqa: SLF001 the surface the shape holds, which it does not expose

    def test_a_tile_is_sampled_once_whatever_it_is_asked(self):
        ground = CountingGround()
        cached = SampledGround(ground, spacing=0.5, tile=32.0)
        rng = np.random.default_rng(3)
        for _ in range(50):
            cached.sample(rng.uniform(1.0, 30.0, 49), rng.uniform(1.0, 30.0, 49))
        assert ground.calls == 1

    def test_a_scalar_and_an_array_of_any_shape_are_answered_in_kind(self):
        cached = SampledGround(CountingGround(), spacing=0.5)
        assert np.shape(cached.sample(3.0, 4.0)) == ()
        assert cached.sample(np.zeros((3, 4)), np.zeros((3, 4))).shape == (3, 4)

    def test_points_across_tile_edges_agree_with_the_ground(self):
        ground = CountingGround()
        cached = SampledGround(ground, spacing=0.5, tile=32.0)
        x = np.array([31.99, 32.0, 32.01, 63.99, 64.0, -0.01, 0.0])
        assert cached.sample(x, x[::-1]) == pytest.approx(ground.sample(x, x[::-1]), abs=2e-3)

    def test_its_normals_are_those_of_the_ground(self):
        class Plane:
            def sample(self, x, z):
                return 0.3 * np.asarray(x, dtype='d') - 0.1 * np.asarray(z, dtype='d')

        cached = SampledGround(Plane(), spacing=0.5)
        x, z = np.array([3.0, 40.0, -70.0]), np.array([1.0, -20.0, 33.0])
        normals = cached.normal(x, z)
        expected = np.array([-0.3, 1.0, 0.1]) / np.linalg.norm([-0.3, 1.0, 0.1])
        assert normals.shape == (3, 3)
        for normal in normals:
            assert normal == pytest.approx(expected, abs=1e-6)

    def test_its_normals_across_tiles_are_unit_vectors_of_the_slope(self):
        cached = SampledGround(CountingGround(), spacing=0.5, tile=32.0)
        rng = np.random.default_rng(5)
        x, z = rng.uniform(-100, 100, (2, 200))
        normals = cached.normal(x, z)
        assert np.linalg.norm(normals, axis=-1) == pytest.approx(1.0)
        slope_x = (cached.sample(x + 0.1, z) - cached.sample(x - 0.1, z)) / 0.2
        assert (-normals[:, 0] / normals[:, 1]) == pytest.approx(slope_x, abs=0.05)

    def test_a_height_and_the_normal_at_the_same_points_are_read_once(self):
        cached = SampledGround(CountingGround(), spacing=0.5)
        x, z = np.array([3.0, 4.0, 5.0]), np.array([1.0, 2.0, 3.0])
        reads = []
        original = cached._read  # noqa: SLF001 counting the reads the cache makes
        cached._read = lambda *a: reads.append(a) or original(*a)  # noqa: SLF001 the reads the cache makes are what is counted
        height = cached.sample(x, z)
        normal = cached.normal(x, z)
        assert len(reads) == 1
        assert height.shape == (3,) and normal.shape == (3, 3)

    def test_changed_points_are_read_again(self):
        cached = SampledGround(CountingGround(), spacing=0.5)
        x, z = np.array([3.0, 4.0]), np.array([1.0, 2.0])
        first = cached.sample(x, z)
        x[0] = 30.0
        assert cached.sample(x, z)[0] != first[0]

    def test_the_tiles_around_a_point_are_made_ahead_of_the_asking(self):
        ground = CountingGround()
        cached = SampledGround(ground, spacing=0.5, tile=32.0)
        cached.prefetch(10.0, 10.0)
        assert cached.wait(10.0)
        assert cached.tile_count == 9
        calls = ground.calls
        cached.sample(np.array([-20.0, 40.0]), np.array([45.0, -30.0]))
        assert ground.calls == calls
        cached.close()

    def test_making_tiles_ahead_does_not_hold_up_the_caller(self):
        class Slow(CountingGround):
            def sample(self, x, z):
                time.sleep(0.05)
                return super().sample(x, z)

        cached = SampledGround(Slow(), spacing=1.0, tile=16.0)
        started = time.perf_counter()
        cached.prefetch(0.0, 0.0)
        assert time.perf_counter() - started < 0.04
        assert cached.wait(10.0)
        cached.close()

    def test_a_tile_asked_for_while_it_is_made_ahead_is_not_made_twice_by_the_asking(self):
        ground = CountingGround()
        cached = SampledGround(ground, spacing=0.5, tile=32.0)
        cached.prefetch(10.0, 10.0)
        cached.wait(10.0)
        cached.prefetch(10.0, 10.0)
        cached.wait(10.0)
        assert ground.calls == 9
        cached.close()

    def test_tiles_asked_for_ahead_are_made_nearest_first(self):
        order = []

        class Ordered(CountingGround):
            def sample(self, x, z):
                order.append((round(float(x[0, 0]) / 32.0), round(float(z[0, 0]) / 32.0)))
                return super().sample(x, z)

        cached = SampledGround(Ordered(), spacing=1.0, tile=32.0)
        cached.prefetch(10.0, 10.0)
        cached.wait(10.0)
        assert order[0] == (0, 0)
        cached.close()

    def test_the_tiles_it_keeps_are_bounded(self):
        cached = SampledGround(CountingGround(), spacing=1.0, tile=16.0, kept=4)
        for k in range(20):
            cached.sample(np.array([k * 16.0 + 1.0]), np.array([1.0]))
        assert cached.tile_count <= 4

    def test_threads_asking_together_get_the_same_answers(self):
        ground = CountingGround()
        cached = SampledGround(ground, spacing=0.5, tile=32.0, kept=8)
        rng = np.random.default_rng(4)
        x, z = rng.uniform(-100, 100, 4000), rng.uniform(-100, 100, 4000)
        expected = ground.sample(x, z)
        failures = []

        def ask(offset):
            for start in range(offset, 4000, 400):
                piece = slice(start, start + 100)
                got = cached.sample(x[piece], z[piece])
                if not np.allclose(got, expected[piece], atol=2e-3):
                    failures.append(start)

        threads = [threading.Thread(target=ask, args=(k * 100,)) for k in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert failures == []


# -- rocks near a focus ----------------------------------------------------------

class Rocks:
    """What a rock field answers: domes about points, as ``mounds_near`` does."""

    def __init__(self, domes):
        self.domes = domes
        self.asked = []

    def __call__(self, x, z, reach):
        self.asked.append((x, z, reach))
        keep = [d for d in self.domes if abs(d[0] - x) <= reach and abs(d[2] - z) <= reach]
        if not keep:
            return (np.zeros((0, 3), 'f'), np.zeros(0, 'f'), np.zeros(0, 'f'), np.zeros(0, 'f'))
        positions = np.array([d[:3] for d in keep], 'f')
        return (positions, np.array([d[3] for d in keep], 'f'),
                np.array([d[4] for d in keep], 'f'), np.array([d[5] for d in keep], 'f'))


def dome(x, z, radius=1.0, rim=0.1, top=0.5, y=0.0):
    return (x, y, z, radius, rim, top)


class TestDomeShape:
    def test_it_rises_from_the_rim_to_the_top(self, physics):
        physics.add_static(None, proxy=dome_proxy(1.0, 0.1, 0.5))
        top = physics.raycast((0.0, 5.0, 0.0), (0.0, -1.0, 0.0))
        assert top.point[1] == pytest.approx(0.5, abs=0.02)
        edge = physics.raycast((0.9, 5.0, 0.0), (0.0, -1.0, 0.0))
        assert 0.1 <= edge.point[1] <= 0.5

    def test_it_is_as_wide_as_its_radius(self, physics):
        physics.add_static(None, proxy=dome_proxy(1.0, 0.1, 0.5))
        assert physics.raycast((3.0, 0.05, 0.0), (-1.0, 0.0, 0.0)).point[0] \
            == pytest.approx(1.0, abs=0.02)

    def test_alike_measurements_make_the_same_proxy(self):
        assert dome_proxy(1.001, 0.1, 0.5) is dome_proxy(1.004, 0.1, 0.5)
        assert dome_proxy(1.0, 0.1, 0.5) is not dome_proxy(1.2, 0.1, 0.5)

    def test_it_is_a_proxy(self):
        assert isinstance(dome_proxy(1.0, 0.1, 0.5), Proxy)


class TestNearbyColliders:
    def test_rocks_within_reach_get_bodies(self, physics):
        rocks = Rocks([dome(2.0, 0.0), dome(60.0, 0.0)])
        physics.add_collider_source(NearbyColliders(rocks, reach=20.0), focus=lambda: (0, 0, 0))
        physics.frame(0.02)
        assert physics.raycast((2.0, 5.0, 0.0), (0, -1, 0)).point[1] == pytest.approx(0.5, abs=0.02)
        assert physics.raycast((60.0, 5.0, 0.0), (0, -1, 0)) is None

    def test_rocks_are_made_as_the_focus_nears_them_and_dropped_as_it_leaves(self, physics):
        rocks = Rocks([dome(60.0, 0.0)])
        focus = [0.0, 0.0, 0.0]
        physics.add_collider_source(NearbyColliders(rocks, reach=20.0, refresh=1.0),
                                    focus=lambda: tuple(focus))
        physics.frame(0.02)
        assert physics.raycast((60.0, 5.0, 0.0), (0, -1, 0)) is None
        focus[0] = 50.0
        physics.frame(0.02)
        assert physics.raycast((60.0, 5.0, 0.0), (0, -1, 0)) is not None
        focus[0] = -100.0
        physics.frame(0.02)
        physics.frame(0.02)
        assert physics.raycast((60.0, 5.0, 0.0), (0, -1, 0)) is None

    def test_a_rock_just_past_reach_is_kept_once_it_has_been_made(self):
        rocks = Rocks([dome(21.0, 0.0)])
        source = NearbyColliders(rocks, reach=20.0, refresh=0.5)
        assert source.update((0.0, 0.0, 0.0)).add == []
        assert len(source.update((5.0, 0.0, 0.0)).add) == 1
        changes = source.update((-0.5, 0.0, 0.0))
        assert changes.add == [] and changes.remove == []

    def test_a_focus_that_has_hardly_moved_asks_the_field_nothing(self):
        rocks = Rocks([dome(2.0, 0.0)])
        source = NearbyColliders(rocks, reach=20.0, refresh=2.0)
        source.update((0.0, 0.0, 0.0))
        source.update((0.5, 0.0, 0.5))
        source.update((1.0, 0.0, 0.0))
        assert len(rocks.asked) == 1
        source.update((3.0, 0.0, 0.0))
        assert len(rocks.asked) == 2

    def test_a_rock_is_added_once_and_removed_once(self):
        rocks = Rocks([dome(2.0, 0.0)])
        source = NearbyColliders(rocks, reach=20.0, refresh=0.0)
        first = source.update((0.0, 0.0, 0.0))
        again = source.update((0.1, 0.0, 0.0))
        assert len(first.add) == 1 and again.add == []
        gone = source.update((500.0, 0.0, 0.0))
        assert len(gone.remove) == 1 and gone.add == []
        assert gone.remove[0] == first.add[0][0]

    def test_rocks_of_alike_size_share_a_shape(self):
        rocks = Rocks([dome(2.0, 0.0), dome(5.0, 5.0)])
        added = NearbyColliders(rocks, reach=20.0).update((0.0, 0.0, 0.0)).add
        assert added[0][1] is added[1][1]

    def test_a_field_that_answers_columns_only_makes_cylinders_pushed_out_of_at_any_height(
            self, physics):
        def posts(x, z, reach):
            return np.array([[3.0, 0.0, 0.0]], 'f'), np.array([0.4], 'f')

        physics.add_collider_source(NearbyColliders(posts, reach=20.0, height=6.0, sink=0.5),
                                    focus=lambda: (0, 0, 0))
        physics.frame(0.02)
        assert physics.raycast((3.0, 20.0, 0.0), (0, -1, 0)).point[1] == pytest.approx(5.5, abs=0.02)
        assert physics.raycast((0.0, 3.0, 0.0), (1, 0, 0)).point[0] == pytest.approx(2.6, abs=0.02)

    def test_a_walker_climbs_the_dome_it_can_step_onto(self, physics):
        Landscape(physics, flat_field(height=0.0))
        rocks = Rocks([dome(0.0, -6.0, radius=1.5, rim=0.1, top=0.4)])
        me = physics.add_character(position=(0.0, 0.0, 0.0))
        physics.add_collider_source(NearbyColliders(rocks, reach=20.0),
                                    focus=lambda: me.position)
        me.set_move((0, 0, -1))
        highest = 0.0
        for _ in range(60 * 5):
            physics.frame(1 / 60)
            highest = max(highest, me.position[1])
        assert highest > 0.35
        assert me.position[2] < -8.0

    def test_a_walker_is_stopped_by_a_dome_too_tall_to_step_onto(self, physics):
        Landscape(physics, flat_field(height=0.0))
        rocks = Rocks([dome(0.0, -6.0, radius=1.5, rim=0.9, top=1.4)])
        me = physics.add_character(position=(0.0, 0.0, 0.0))
        physics.add_collider_source(NearbyColliders(rocks, reach=20.0), focus=lambda: me.position)
        me.set_move((0, 0, -1))
        for _ in range(60 * 6):
            physics.frame(1 / 60)
        assert np.hypot(me.position[0], me.position[2] + 6.0) >= 1.5 + me.capabilities.radius - 0.05
        assert me.position[1] == pytest.approx(0.0, abs=0.05)
