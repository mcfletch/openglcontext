"""Ground to stand on, when the ground is a height field rather than tiles.

A world small enough to hold one splat terrain has no streamed ground tiles for
:class:`~OpenGLContext.loaders.tiles3d.physics_colliders.TerrainColliders` to
turn into colliders, so the field itself has to provide them. It is cut into
square chunks and the ones near whatever is moving are in the physics world;
the rest are not, because a four-kilometre field is half a million triangles and
a car only ever touches four of them at a time.
"""
import numpy as np
import pytest

from omi_physics.raycast import raycast
from omi_physics.world import PhysicsWorld
from OpenGLContext.physics.heightfield import HeightFieldColliders
from OpenGLContext.scenegraph.terrain.heightfield import HeightField

EXTENT = 1024.0


def _hilly(x, z):
    return 30.0 * np.sin(np.asarray(x, 'd') / 200.0) \
        + 20.0 * np.cos(np.asarray(z, 'd') / 150.0)


def _field(res=129):
    return HeightField.from_function(_hilly, res=res, extent=EXTENT)


def _ground_under(world, x, z):
    hit = raycast(world, (x, 400.0, z), (0.0, -1.0, 0.0), max_distance=900.0)
    return None if hit is None else float(hit.point[1])


class TestTheGroundIsThere:
    def test_a_ray_finds_the_field_under_the_camera(self) -> None:
        world = PhysicsWorld()
        ground = HeightFieldColliders(world, _field(), reach=300.0)
        ground.update((0.0, 0.0, 0.0))
        assert _ground_under(world, 0.0, 0.0) == pytest.approx(
            _hilly(0.0, 0.0), abs=1.0)

    def test_it_agrees_with_the_field_it_was_built_from(self) -> None:
        field = _field()
        world = PhysicsWorld()
        HeightFieldColliders(world, field, reach=300.0).update((0.0, 0.0, 0.0))
        for x, z in ((40.0, -30.0), (-120.0, 90.0), (10.0, 10.0)):
            assert _ground_under(world, x, z) == pytest.approx(
                float(field.sample(x, z)), abs=0.5)

    def test_ground_out_of_reach_is_not_loaded(self) -> None:
        world = PhysicsWorld()
        HeightFieldColliders(world, _field(), reach=200.0).update((0.0, 0.0, 0.0))
        assert _ground_under(world, 480.0, 480.0) is None

    def test_moving_brings_the_ground_with_you(self) -> None:
        world = PhysicsWorld()
        ground = HeightFieldColliders(world, _field(), reach=200.0)
        ground.update((0.0, 0.0, 0.0))
        ground.update((450.0, 0.0, 450.0))
        assert _ground_under(world, 450.0, 450.0) is not None

    def test_what_you_left_behind_goes_away(self) -> None:
        """An hour of driving costs what one view of the world costs: after a
        drive across the map, exactly the ground a standing start there
        holds."""
        field = _field()
        arrived = (450.0, 0.0, 450.0)
        driven = HeightFieldColliders(PhysicsWorld(), field, reach=200.0)
        for step in range(7):
            driven.update((-450.0 + step * 150.0, 0.0, -450.0 + step * 150.0))
        driven.update(arrived)
        standing = HeightFieldColliders(PhysicsWorld(), field, reach=200.0)
        standing.update(arrived)
        assert driven.chunk_count() == standing.chunk_count()

    def test_standing_still_reloads_nothing(self) -> None:
        world = PhysicsWorld()
        ground = HeightFieldColliders(world, _field(), reach=200.0)
        ground.update((0.0, 0.0, 0.0))
        before = ground.chunk_count()
        ground.update((0.0, 0.0, 0.0))
        ground.update((1.0, 0.0, 1.0))
        assert ground.chunk_count() == before

    def test_the_whole_field_can_be_loaded_at_once(self) -> None:
        field = _field(res=65)
        world = PhysicsWorld()
        ground = HeightFieldColliders(world, field, reach=EXTENT)
        ground.update((0.0, 0.0, 0.0))
        assert _ground_under(world, 500.0, -500.0) is not None


class TestHowItIsCutUp:
    def test_the_chunks_cover_the_field_without_gaps(self) -> None:
        """A seam between two chunks is a hole a wheel falls through."""
        field = _field(res=129)
        world = PhysicsWorld()
        HeightFieldColliders(world, field, reach=EXTENT,
                             chunk=128.0).update((0.0, 0.0, 0.0))
        edge = np.linspace(-500.0, 500.0, 97)
        for x in edge:
            assert _ground_under(world, float(x), 0.0) is not None

    def test_a_chunk_meets_its_neighbour_at_the_same_height(self) -> None:
        field = _field(res=129)
        world = PhysicsWorld()
        HeightFieldColliders(world, field, reach=EXTENT,
                             chunk=128.0).update((0.0, 0.0, 0.0))
        # Either side of a chunk boundary the surface must not step.
        for boundary in (-256.0, -128.0, 0.0, 128.0, 256.0):
            low = _ground_under(world, boundary - 0.05, 30.0)
            high = _ground_under(world, boundary + 0.05, 30.0)
            assert abs(low - high) < 0.1

    def test_a_coarser_field_costs_fewer_triangles(self) -> None:
        world = PhysicsWorld()
        fine = HeightFieldColliders(world, _field(res=129), reach=EXTENT)
        fine.update((0.0, 0.0, 0.0))
        coarse = HeightFieldColliders(PhysicsWorld(), _field(res=33),
                                      reach=EXTENT)
        coarse.update((0.0, 0.0, 0.0))
        assert coarse.triangle_count() < fine.triangle_count()

    def test_it_reports_what_it_is_holding(self) -> None:
        world = PhysicsWorld()
        ground = HeightFieldColliders(world, _field(), reach=200.0)
        assert ground.chunk_count() == 0
        ground.update((0.0, 0.0, 0.0))
        assert ground.chunk_count() > 0

    def test_letting_go_of_everything_empties_it(self) -> None:
        world = PhysicsWorld()
        ground = HeightFieldColliders(world, _field(), reach=200.0)
        ground.update((0.0, 0.0, 0.0))
        ground.clear()
        assert ground.chunk_count() == 0
        assert _ground_under(world, 0.0, 0.0) is None


class TestACarOnIt:
    def test_a_car_settles_on_the_field_and_stays_there(self) -> None:
        from omi_physics import model
        from omi_physics.vehicle import RaycastVehicle, VehicleTuning, car_wheels
        field = _field()
        world = PhysicsWorld()
        ground = HeightFieldColliders(world, field, reach=300.0)
        ground.update((0.0, 0.0, 0.0))
        body = world.add_body(model.Motion(type=model.DYNAMIC, mass=1200.0),
                              position=(0.0, float(field.sample(0.0, 0.0)) + 4.0,
                                        0.0))
        car = RaycastVehicle(world, body, car_wheels(), VehicleTuning())
        for _step in range(360):
            car.control()
            car.update(1.0 / 120.0)
            world.step(1.0 / 120.0)
        resting = float(world.position[body][1]) - float(field.sample(
            float(world.position[body][0]), float(world.position[body][2])))
        assert resting == pytest.approx(0.64, abs=0.4)


class TestAVoidUnderTheGround:
    """A bore runs *inside* the hill, and the hill's own surface is still drawn
    over it. Left in the physics world the surface is a wall across the road, so
    the collider is cut where something passes through."""

    def _tunnel_line(self):
        """A straight bore along z = 0, from x = -200 to x = 200."""
        return -200.0, 200.0, 25.0

    def _holed(self, world, **named):
        low, high, width = self._tunnel_line()

        def bore(x, z):
            return (x >= low) & (x <= high) & (np.abs(z) <= width)
        return HeightFieldColliders(world, _field(), reach=EXTENT, holes=bore,
                                    **named)

    def test_the_ground_over_the_bore_is_gone(self) -> None:
        world = PhysicsWorld()
        self._holed(world).update((0.0, 0.0, 0.0))
        assert _ground_under(world, 0.0, 0.0) is None

    def test_the_ground_beside_it_is_still_there(self) -> None:
        world = PhysicsWorld()
        self._holed(world).update((0.0, 0.0, 0.0))
        assert _ground_under(world, 0.0, 200.0) is not None

    def test_the_ground_past_its_end_is_still_there(self) -> None:
        world = PhysicsWorld()
        self._holed(world).update((0.0, 0.0, 0.0))
        assert _ground_under(world, 400.0, 0.0) is not None

    def test_a_chunk_entirely_inside_a_hole_is_not_added(self) -> None:
        """An empty trimesh in the broadphase is a body to test against for
        nothing."""
        every = HeightFieldColliders(PhysicsWorld(), _field(), reach=EXTENT,
                                     chunk=64.0)
        every.update((0.0, 0.0, 0.0))
        wide = HeightFieldColliders(
            PhysicsWorld(), _field(), reach=EXTENT, chunk=64.0,
            holes=lambda x, z: (np.abs(x) <= 200.0) & (np.abs(z) <= 200.0))
        wide.update((0.0, 0.0, 0.0))
        assert wide.chunk_count() < every.chunk_count()

    def test_without_holes_nothing_is_cut(self) -> None:
        world = PhysicsWorld()
        HeightFieldColliders(world, _field(), reach=EXTENT).update((0, 0, 0))
        assert _ground_under(world, 0.0, 0.0) is not None

    def test_a_hole_that_covers_everything_leaves_no_ground(self) -> None:
        world = PhysicsWorld()
        HeightFieldColliders(world, _field(), reach=EXTENT,
                             holes=lambda x, z: np.ones(np.shape(x), bool)
                             ).update((0.0, 0.0, 0.0))
        assert _ground_under(world, 0.0, 0.0) is None
        assert _ground_under(world, 300.0, -300.0) is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))