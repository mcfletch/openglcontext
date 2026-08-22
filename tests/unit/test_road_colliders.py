"""The carriageway as a collider, built from the road rather than from tiles.

Tile geometry is level-of-detail geometry: the same road at whatever resolution
the streamer picked, and the resolution changes as a car drives. Two
resolutions of one curve are a metre apart, so the surface under the wheels
steps as the streamer refines -- which at a hundred and thirty is indis-
tinguishable from hitting a wall.

A road is a centreline and a cross-section, and a game already has both. Built
from those, the collider is one surface at one resolution, everywhere, always.
"""
import numpy as np
import pytest

from omi_physics.raycast import raycast
from omi_physics.world import PhysicsWorld
from OpenGLContext.physics.road import RoadColliders
from OpenGLContext.scenegraph.road import RoadProfile

PROFILE = RoadProfile()

#: The heading that points a car along +X, which is the way these roads run.
#: A heading is measured round from -Z, and the drive is along the car's nose.
_EAST = -np.pi / 2.0

#: Where a car starts on them: in from the end, so it is on the surface rather
#: than on the rim of it.
_START = (200.0, 1.0, 0.0)


def _straight(length=1200.0, spacing=6.0, grade=0.0):
    x = np.arange(0.0, length + spacing, spacing)
    return np.stack([x, x * grade, np.zeros(len(x))], axis=-1)


def _ring(radius=400.0, points=400, height=20.0):
    angle = np.linspace(0.0, 2 * np.pi, points, endpoint=False)
    return np.stack([radius * np.cos(angle), np.full(points, height),
                     radius * np.sin(angle)], axis=-1)


def _surface(world, x, z):
    hit = raycast(world, (x, 400.0, z), (0.0, -1.0, 0.0), max_distance=800.0)
    return None if hit is None else float(hit.point[1])


class TestTheRoadIsThere:
    def test_a_ray_finds_the_carriageway(self) -> None:
        world = PhysicsWorld()
        RoadColliders(world, _straight(), PROFILE, reach=200.0).update(
            (0.0, 0.0, 0.0))
        assert _surface(world, 60.0, 0.0) == pytest.approx(0.0, abs=0.05)

    def test_it_follows_the_road_up_a_grade(self) -> None:
        world = PhysicsWorld()
        line = _straight(grade=0.08)
        RoadColliders(world, line, PROFILE, reach=300.0).update((0.0, 0.0, 0.0))
        assert _surface(world, 200.0, 0.0) == pytest.approx(16.0, abs=0.1)

    def test_it_is_as_wide_as_the_road(self) -> None:
        world = PhysicsWorld()
        RoadColliders(world, _straight(), PROFILE, reach=200.0).update(
            (0.0, 0.0, 0.0))
        half = PROFILE.total_width / 2.0
        assert _surface(world, 60.0, half - 0.3) is not None
        assert _surface(world, 60.0, half + 2.0) is None

    def test_it_cambers_like_the_road(self) -> None:
        world = PhysicsWorld()
        RoadColliders(world, _straight(), PROFILE, reach=200.0).update(
            (0.0, 0.0, 0.0))
        crown = _surface(world, 60.0, 0.0)
        edge = _surface(world, 60.0, PROFILE.carriageway_width / 2.0 - 0.1)
        assert crown > edge

    def test_road_out_of_reach_is_not_loaded(self) -> None:
        world = PhysicsWorld()
        RoadColliders(world, _straight(), PROFILE, reach=150.0).update(
            (0.0, 0.0, 0.0))
        assert _surface(world, 900.0, 0.0) is None

    def test_moving_brings_the_road_with_you(self) -> None:
        world = PhysicsWorld()
        road = RoadColliders(world, _straight(), PROFILE, reach=150.0)
        road.update((0.0, 0.0, 0.0))
        road.update((900.0, 0.0, 0.0))
        assert _surface(world, 900.0, 0.0) is not None

    def test_what_you_left_behind_goes_away(self) -> None:
        line = _straight()
        driven = RoadColliders(PhysicsWorld(), line, PROFILE, reach=150.0)
        for step in range(10):
            driven.update((step * 120.0, 0.0, 0.0))
        standing = RoadColliders(PhysicsWorld(), line, PROFILE, reach=150.0)
        standing.update((9 * 120.0, 0.0, 0.0))
        assert driven.chunk_count() == standing.chunk_count()

    def test_standing_still_rebuilds_nothing(self) -> None:
        world = PhysicsWorld()
        road = RoadColliders(world, _straight(), PROFILE, reach=150.0)
        road.update((300.0, 0.0, 0.0))
        before = road.triangle_count()
        road.update((301.0, 0.0, 0.0))
        assert road.triangle_count() == before


class TestOneSurfaceEverywhere:
    """The point of it: the surface does not change as you drive."""

    def test_the_height_under_a_point_never_changes(self) -> None:
        line = _ring()
        road = RoadColliders(PhysicsWorld(), line, PROFILE, reach=200.0)
        world = road.world
        watched = line[100]
        seen = set()
        for at in line[::20]:
            road.update(at)
            found = _surface(world, float(watched[0]), float(watched[2]))
            if found is not None:
                seen.add(round(found, 4))
        assert len(seen) == 1, "the surface moved: %r" % (sorted(seen),)

    def test_a_closed_road_joins_up(self) -> None:
        line = _ring()
        world = PhysicsWorld()
        RoadColliders(world, line, PROFILE, reach=4000.0,
                      closed=True).update((0.0, 0.0, 0.0))
        # Right at the join between the last point and the first.
        between = 0.5 * (line[-1] + line[0])
        between *= 400.0 / float(np.hypot(between[0], between[2]))
        assert _surface(world, float(between[0]), float(between[2])) is not None

    def test_an_open_road_does_not(self) -> None:
        line = _straight(length=600.0)
        world = PhysicsWorld()
        RoadColliders(world, line, PROFILE, reach=4000.0).update((0, 0, 0))
        assert _surface(world, -30.0, 0.0) is None

    def test_the_chunks_meet_without_a_seam(self) -> None:
        line = _straight(length=1200.0)
        world = PhysicsWorld()
        RoadColliders(world, line, PROFILE, reach=4000.0,
                      chunk=100.0).update((600.0, 0.0, 0.0))
        for x in np.linspace(2.0, 1198.0, 200):
            assert _surface(world, float(x), 0.0) is not None, "gap at %.0f" % x


class TestACarOnIt:
    def _driven(self, seconds=25.0):
        """A car at full throttle along a long straight, and where it got to."""
        from omi_physics import model
        from omi_physics.vehicle import RaycastVehicle, VehicleTuning, car_wheels
        line = _straight(length=3000.0)
        world = PhysicsWorld()
        road = RoadColliders(world, line, PROFILE, reach=250.0)
        road.update(_START)
        body = world.add_body(model.Motion(type=model.DYNAMIC, mass=1200.0),
                              position=_START)
        car = RaycastVehicle(world, body, car_wheels(), VehicleTuning())
        car.place(_START, _EAST)
        worst = 0.0
        for step in range(int(seconds * 120)):
            if step % 30 == 0:
                road.update(world.position[body])
            car.control(throttle=1.0)
            car.update(1.0 / 120.0)
            world.step(1.0 / 120.0)
            if step > 240:
                worst = max(worst, abs(float(world.position[body][1]) - 0.7))
        return float(world.position[body][0]), worst

    def test_a_car_drives_along_it_without_being_stopped(self) -> None:
        assert self._driven()[0] > 700.0

    def test_it_stays_on_the_surface_the_whole_way(self) -> None:
        """Across every chunk boundary it crosses: no step, no launch."""
        assert self._driven()[1] < 0.2


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestTheEdgeOfADeck:
    """A car that runs wide on a bridge goes off it: there is nothing beside a
    deck but the thing the bridge was built over.

    The barrier the structure is drawn with is what stops that, and a barrier
    that is drawn and not collided with stops nothing. So the stretches a
    caller says are carried get a wall along each edge, and a car meets it.
    """

    def _world(self, barriers=(), **kwargs):
        world = PhysicsWorld()
        road = RoadColliders(world, _straight(), PROFILE, barriers=barriers,
                             **kwargs)
        road.update(np.array(_START))
        return world, road

    @staticmethod
    def _sideways(world, x, z, towards):
        """Fire across the road at the height a car's body is, and see what
        stops it. Not over the top of the barrier: what is being asked is what
        the car meets, and half a metre up is where the car is."""
        return raycast(world, (x, 0.5, z), (0.0, 0.0, float(towards)),
                       max_distance=40.0)

    def test_a_road_on_the_ground_has_no_edge_to_fall_off(self) -> None:
        world, _road = self._world()
        assert self._sideways(world, 200.0, 0.0, 1.0) is None

    def test_a_carried_stretch_has_a_wall_each_side(self) -> None:
        world, _road = self._world(barriers=[(0.0, 1200.0)])
        for towards in (1.0, -1.0):
            hit = self._sideways(world, 200.0, 0.0, towards)
            assert hit is not None, 'nothing beside the deck at %+.0f' % towards

    def test_the_wall_is_at_the_edge_rather_than_across_the_road(self) -> None:
        world, _road = self._world(barriers=[(0.0, 1200.0)])
        hit = self._sideways(world, 200.0, 0.0, 1.0)
        # The inner face of the wall, which stands its own width inside the
        # edge of the deck.
        half = PROFILE.on_structure().total_width / 2.0
        assert hit.distance == pytest.approx(half, abs=0.5)
        assert hit.distance > PROFILE.carriageway_width / 2.0

    def test_only_the_stretch_that_is_carried_gets_one(self) -> None:
        world, road = self._world(barriers=[(400.0, 800.0)])
        road.update(np.array([600.0, 1.0, 0.0]))
        assert self._sideways(world, 600.0, 0.0, 1.0) is not None
        assert self._sideways(world, 1150.0, 0.0, 1.0) is None

    def test_it_is_still_the_road_underneath(self) -> None:
        """A barrier beside the carriageway is not a barrier over it."""
        world, _road = self._world(barriers=[(0.0, 1200.0)])
        assert _surface(world, 200.0, 0.0) == pytest.approx(0.0, abs=0.1)

    def test_the_triangles_are_counted_with_the_rest(self) -> None:
        _world, plain = self._world()
        _world2, walled = self._world(barriers=[(0.0, 1200.0)])
        assert walled.triangle_count() > plain.triangle_count()

    def test_a_chunk_let_go_takes_its_wall_with_it(self) -> None:
        world, road = self._world(barriers=[(0.0, 1200.0)])
        road.clear()
        assert road.triangle_count() == 0
        assert self._sideways(world, 200.0, 0.0, 1.0) is None
