"""Ground to stand on, when the ground is a height field rather than tiles.

A world small enough to hold one splat terrain has no streamed ground tiles for
:class:`~OpenGLContext.loaders.tiles3d.physics_colliders.TerrainColliders` to
turn into colliders, so the field itself provides them. It is cut into square
chunks and the ones near the focus are bodies of the physics service; the rest
are not, because a four-kilometre field is half a million triangles and a car
only ever touches four of them at a time.
"""
import numpy as np
import pytest

from OpenGLContext.physics.body import Body
from OpenGLContext.physics.heightfield import HeightFieldColliders
from OpenGLContext.scenegraph.terrain.heightfield import HeightField
from tests.unit._streamed import Streamed

#: These tests check a part of the engine built on an omi_physics world, or use
#: omi_physics as their reference; it is the deprecated omi extra.
REASON_OMI = 'omi_physics (the omi extra) is not installed'
raycast = pytest.importorskip('omi_physics.raycast', reason=REASON_OMI).raycast
model = pytest.importorskip('omi_physics.model', reason=REASON_OMI)
RaycastVehicle = pytest.importorskip('omi_physics.vehicle', reason=REASON_OMI).RaycastVehicle
VehicleTuning = pytest.importorskip('omi_physics.vehicle', reason=REASON_OMI).VehicleTuning
car_wheels = pytest.importorskip('omi_physics.vehicle', reason=REASON_OMI).car_wheels

pytestmark = pytest.mark.engines('omi', reason='reads the omi world the colliders are made in')

EXTENT = 1024.0


def _hilly(x, z):
    return 30.0 * np.sin(np.asarray(x, 'd') / 200.0) \
        + 20.0 * np.cos(np.asarray(z, 'd') / 150.0)


def _field(res=129):
    return HeightField.from_function(_hilly, res=res, extent=EXTENT)


def _ground(field=None, **named):
    return Streamed(HeightFieldColliders(field if field is not None else _field(), **named))


def _ground_under(ground, x, z):
    hit = raycast(ground.world, (x, 400.0, z), (0.0, -1.0, 0.0), max_distance=900.0)
    return None if hit is None else float(hit.point[1])


class TestASource:
    def test_each_chunk_is_a_body_of_the_service(self) -> None:
        ground = _ground(reach=300.0)
        ground.update((0.0, 0.0, 0.0))
        hit = ground.physics.raycast((0.0, 400.0, 0.0), (0.0, -1.0, 0.0), 900.0)
        assert isinstance(hit.body, Body)
        assert hit.body.kind == 'static'

    def test_it_answers_what_changed(self) -> None:
        source = HeightFieldColliders(_field(), reach=200.0)
        first = source.update((0.0, 0.0, 0.0))
        assert len(first.add) == source.chunk_count() > 0
        assert not first.remove
        again = source.update((0.0, 0.0, 0.0))
        assert not again.add and not again.remove

    def test_moving_away_names_the_chunks_left_behind(self) -> None:
        source = HeightFieldColliders(_field(), reach=150.0)
        held = {one[0] for one in source.update((-400.0, 0.0, -400.0)).add}
        gone = set(source.update((400.0, 0.0, 400.0)).remove)
        assert gone == held

    def test_removing_the_source_takes_its_bodies_and_starts_it_afresh(self) -> None:
        ground = _ground(reach=200.0)
        ground.update((0.0, 0.0, 0.0))
        ground.clear()
        assert ground.chunk_count() == 0
        assert _ground_under(ground, 0.0, 0.0) is None


class TestTheGroundIsThere:
    def test_a_ray_finds_the_field_under_the_camera(self) -> None:
        ground = _ground(reach=300.0)
        ground.update((0.0, 0.0, 0.0))
        assert _ground_under(ground, 0.0, 0.0) == pytest.approx(
            _hilly(0.0, 0.0), abs=1.0)

    def test_it_agrees_with_the_field_it_was_built_from(self) -> None:
        field = _field()
        ground = _ground(field, reach=300.0)
        ground.update((0.0, 0.0, 0.0))
        for x, z in ((40.0, -30.0), (-120.0, 90.0), (10.0, 10.0)):
            assert _ground_under(ground, x, z) == pytest.approx(
                float(field.sample(x, z)), abs=0.5)

    def test_ground_out_of_reach_is_not_loaded(self) -> None:
        ground = _ground(reach=200.0)
        ground.update((0.0, 0.0, 0.0))
        assert _ground_under(ground, 480.0, 480.0) is None

    def test_moving_brings_the_ground_with_you(self) -> None:
        ground = _ground(reach=200.0)
        ground.update((0.0, 0.0, 0.0))
        ground.update((450.0, 0.0, 450.0))
        assert _ground_under(ground, 450.0, 450.0) is not None

    def test_what_you_left_behind_goes_away(self) -> None:
        """An hour of driving costs what one view of the world costs: after a
        drive across the map, exactly the ground a standing start there
        holds."""
        field = _field()
        arrived = (450.0, 0.0, 450.0)
        driven = _ground(field, reach=200.0)
        for step in range(7):
            driven.update((-450.0 + step * 150.0, 0.0, -450.0 + step * 150.0))
        driven.update(arrived)
        standing = _ground(field, reach=200.0)
        standing.update(arrived)
        assert driven.chunk_count() == standing.chunk_count()
        assert driven.world.live_body_count == standing.world.live_body_count

    def test_standing_still_reloads_nothing(self) -> None:
        ground = _ground(reach=200.0)
        ground.update((0.0, 0.0, 0.0))
        before = ground.chunk_count()
        ground.update((0.0, 0.0, 0.0))
        ground.update((1.0, 0.0, 1.0))
        assert ground.chunk_count() == before

    def test_the_whole_field_can_be_loaded_at_once(self) -> None:
        ground = _ground(_field(res=65), reach=EXTENT)
        ground.update((0.0, 0.0, 0.0))
        assert _ground_under(ground, 500.0, -500.0) is not None


class TestHowItIsCutUp:
    def test_the_chunks_cover_the_field_without_gaps(self) -> None:
        """A seam between two chunks is a hole a wheel falls through."""
        ground = _ground(_field(res=129), reach=EXTENT, chunk=128.0)
        ground.update((0.0, 0.0, 0.0))
        edge = np.linspace(-500.0, 500.0, 97)
        for x in edge:
            assert _ground_under(ground, float(x), 0.0) is not None

    def test_a_chunk_meets_its_neighbour_at_the_same_height(self) -> None:
        ground = _ground(_field(res=129), reach=EXTENT, chunk=128.0)
        ground.update((0.0, 0.0, 0.0))
        # Either side of a chunk boundary the surface must not step.
        for boundary in (-256.0, -128.0, 0.0, 128.0, 256.0):
            low = _ground_under(ground, boundary - 0.05, 30.0)
            high = _ground_under(ground, boundary + 0.05, 30.0)
            assert abs(low - high) < 0.1

    def test_a_coarser_field_costs_fewer_triangles(self) -> None:
        fine = HeightFieldColliders(_field(res=129), reach=EXTENT)
        fine.update((0.0, 0.0, 0.0))
        coarse = HeightFieldColliders(_field(res=33), reach=EXTENT)
        coarse.update((0.0, 0.0, 0.0))
        assert coarse.triangle_count() < fine.triangle_count()

    def test_it_reports_what_it_is_holding(self) -> None:
        ground = HeightFieldColliders(_field(), reach=200.0)
        assert ground.chunk_count() == 0
        ground.update((0.0, 0.0, 0.0))
        assert ground.chunk_count() > 0

    def test_letting_go_of_everything_empties_it(self) -> None:
        ground = HeightFieldColliders(_field(), reach=200.0)
        ground.update((0.0, 0.0, 0.0))
        ground.clear()
        assert ground.chunk_count() == 0
        assert ground.triangle_count() == 0
        assert ground.update((0.0, 0.0, 0.0)).add


class TestACarOnIt:
    def test_a_car_settles_on_the_field_and_stays_there(self) -> None:
        field = _field()
        ground = _ground(field, reach=300.0)
        ground.update((0.0, 0.0, 0.0))
        world = ground.world
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

    def _holed(self, **named):
        low, high, width = self._tunnel_line()

        def bore(x, z):
            return (x >= low) & (x <= high) & (np.abs(z) <= width)
        ground = _ground(reach=EXTENT, holes=bore, **named)
        ground.update((0.0, 0.0, 0.0))
        return ground

    def test_the_ground_over_the_bore_is_gone(self) -> None:
        assert _ground_under(self._holed(), 0.0, 0.0) is None

    def test_the_ground_beside_it_is_still_there(self) -> None:
        assert _ground_under(self._holed(), 0.0, 200.0) is not None

    def test_the_ground_past_its_end_is_still_there(self) -> None:
        assert _ground_under(self._holed(), 400.0, 0.0) is not None

    def test_a_chunk_entirely_inside_a_hole_is_not_added(self) -> None:
        """An empty trimesh in the broadphase is a body to test against for
        nothing."""
        every = HeightFieldColliders(_field(), reach=EXTENT, chunk=64.0)
        every.update((0.0, 0.0, 0.0))
        wide = HeightFieldColliders(
            _field(), reach=EXTENT, chunk=64.0,
            holes=lambda x, z: (np.abs(x) <= 200.0) & (np.abs(z) <= 200.0))
        added = wide.update((0.0, 0.0, 0.0)).add
        assert wide.chunk_count() == len(added) < every.chunk_count()

    def test_a_chunk_inside_a_hole_is_cut_once(self) -> None:
        """Asked again, a chunk with nothing left of it is not cut again."""
        cuts = []

        def everywhere(x, _z):
            cuts.append(1)
            return np.ones(np.shape(x), bool)
        ground = HeightFieldColliders(_field(), reach=EXTENT, chunk=256.0, holes=everywhere)
        ground.update((0.0, 0.0, 0.0))
        before = len(cuts)
        ground.update((300.0, 0.0, 300.0))
        assert len(cuts) == before

    def test_without_holes_nothing_is_cut(self) -> None:
        ground = _ground(reach=EXTENT)
        ground.update((0.0, 0.0, 0.0))
        assert _ground_under(ground, 0.0, 0.0) is not None

    def test_a_hole_that_covers_everything_leaves_no_ground(self) -> None:
        ground = _ground(reach=EXTENT, holes=lambda x, _z: np.ones(np.shape(x), bool))
        ground.update((0.0, 0.0, 0.0))
        assert _ground_under(ground, 0.0, 0.0) is None
        assert _ground_under(ground, 300.0, -300.0) is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
