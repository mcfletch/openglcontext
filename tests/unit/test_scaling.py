"""How the engine's per-frame work grows with the scene, held by ``check_scaling``.

Each test measures one subsystem at a size and at four times it, through
:func:`OpenGLContext.testing.scaling.check_scaling`, and bounds the ratio: work
that should not depend on the scene's size at about 1, work that is linear in
it at about 4. The subsystems are the ones whose cost in a large world was a
review's finding: zones classifying objects, the mirror planner, and ground
cover choosing what it draws. A count is used wherever the work can report
one; the timed tests carry ``serial``.
"""
import numpy as np
import pytest

from OpenGLContext.passes import zonelayers
from OpenGLContext.passes.reflectionplanner import ReflectionPlanner
from OpenGLContext.passes.reflectiontiles import Budget
from OpenGLContext.scenegraph.reflector import PlanarReflector
from OpenGLContext.scenegraph.zone import Zone, ZoneEnvironment
from OpenGLContext.testing.scaling import check_scaling
from tests.unit.test_ground_cover import _cover, _species
from tests.unit.test_pbr_zones import Box, ZonedPass, at
from tests.unit.test_reflection_planner import ATLAS, _behind, _frame, _mirror
from tests.unit.test_zone_layers import place, room

# --- zones ------------------------------------------------------------------


def _street(objects):
    """A room every hundred metres and ten objects a metre... along a street.

    The street's length grows with the number of objects, so the objects near
    any one room stay as many however long it is.
    """
    rooms = max(2, objects // 100)
    zoned = ZonedPass([
        (Zone(size=(10, 10, 10), blend=1.0,
              settings=[ZoneEnvironment(intensity=0.1 * (index % 9 + 1))]),
         at(100.0 * index)) for index in range(rooms)])
    zoned.placeZones()
    zoned.setupZones(np.identity(4))
    records = [(None, None, at(x), Box(0.5), ('thing', index), None)
               for index, x in enumerate(np.linspace(-20.0, 100.0 * rooms - 80.0,
                                                     objects))]
    zoned.refreshZones(records)
    return zoned, records


def test_one_room_moving_classifies_the_objects_near_it_however_long_the_street():
    def prepare(objects):
        zoned, records = _street(objects)
        classified = []
        real = zoned._classify
        zoned._classify = lambda items: classified.append(len(items)) or real(items)
        steps = iter(range(1, 1000))

        def creep():
            classified.clear()
            zoned.paths[Zone][0].matrix = at(0.01 * next(steps))
            zoned.placeZones()
            zoned.refreshZones(records)
            return sum(classified)
        return creep
    check_scaling(prepare, n=1000, most=1.5, measure='count')


def _boxes_along_a_road(objects):
    """``objects`` boxes in no order over a road with a room every 350 of them."""
    rng = np.random.default_rng(32)
    half = objects / 10.0
    table = zonelayers.ZoneTable(place(*[
        (room(size=20.0, blend=5.0, environment=ZoneEnvironment()), (x, 0, 0))
        for x in np.linspace(-half, half, max(2, objects // 350))]))
    lows = rng.uniform(-half, half, (objects, 3)) * (1, 0.005, 0.005)
    return table, lows, lows + 2.0


def test_classifying_touches_the_zones_near_each_object():
    """Each object is carried into the frames of the zones near it, not of every zone."""
    def prepare(objects):
        table, lows, highs = _boxes_along_a_road(objects)
        carried = []
        real = table._local_to

        def counting(which, points):
            carried.append(len(which) * len(points))
            return real(which, points)
        table._local_to = counting

        def classify():
            carried.clear()
            table.classify_many(lows, highs)
            return sum(carried)
        return classify
    check_scaling(prepare, n=5000, most=5.0, measure='count')


@pytest.mark.serial
def test_classifying_a_first_frame_grows_with_the_objects():
    def prepare(objects):
        table, lows, highs = _boxes_along_a_road(objects)
        return lambda: table.classify_many(lows, highs)
    check_scaling(prepare, n=5000, most=6.0, repeat=3)


def test_classifying_answers_as_one_box_at_a_time_does():
    table, lows, highs = _boxes_along_a_road(3000)
    together = table.classify_many(lows, highs)
    for index in range(0, 3000, 97):
        assert ([(placed.zone, inside) for placed, inside in together[index]]
                == [(placed.zone, inside) for placed, inside
                    in table.classify(lows[index], highs[index])])


def test_boxes_along_a_road_are_ordered_along_it():
    rng = np.random.default_rng(3)
    lows = rng.uniform(-500, 500, (200, 3)) * (1, 0.01, 0.01)
    order = zonelayers.spatial_order(lows, lows + 1.0)
    assert sorted(order.tolist()) == list(range(200))
    along = lows[order, 0]
    spans = [np.ptp(along[start:start + 20]) for start in range(0, 200, 20)]
    assert max(spans) < 200.0, spans           # of a road 1,000 m long
    assert zonelayers.spatial_order(lows[:1], lows[:1]).tolist() == [0]


# --- the mirror planner -----------------------------------------------------

BIG = Budget(views=16, separate_views=4, texels=10 ** 9)


@pytest.mark.serial
def test_planning_grows_with_the_mirrors_in_view():
    def prepare(mirrors):
        records = [_mirror(x=0.01 * index, reflector=PlanarReflector(interval=1))
                   for index in range(mirrors)]
        planner, frame = ReflectionPlanner(), _frame(records)
        return lambda: planner.plan([frame], ATLAS, BIG)
    check_scaling(prepare, n=20, most=6.0, repeat=3)


def test_mirrors_facing_mirrors_plan_a_bounded_number_of_bounces():
    """A hall of mirrors followed three bounces deep: not mirrors cubed."""
    def prepare(mirrors):
        front = [_mirror(x=2.0 * index) for index in range(mirrors)]
        back = [_behind(2.0 * index) for index in range(mirrors)]
        planner, frame = ReflectionPlanner(), _frame(front)
        budget = Budget(views=4, separate_views=2, texels=10 ** 9)

        def plan():
            return len(planner.plan([frame], ATLAS, budget,
                                    inside=lambda frame: front + back,
                                    bounces=3).candidates)
        return plan
    check_scaling(prepare, n=4, most=4.5, measure='count')


# --- ground cover -----------------------------------------------------------

class _Counting:
    """The clump layer, counting the instances it is handed."""

    def __init__(self):
        self.handed = 0

    def update_instances(self, positions, yaws, scales, shades=None):
        self.handed += len(positions)


def _walking_cover(density=1.0):
    cover = _cover(card_radius=40.0, clump_radius=30.0,
                   species=_species(density=density))
    rung = cover.rungs[0]
    rung.clumps_near, rung.clumps_far = _Counting(), _Counting()
    cover.update((0.0, 0.0, 0.0))
    return cover, rung


def test_a_walk_hands_the_clumps_as_much_however_many_frames_it_takes():
    """Twenty metres walked in a number of frames: what is copied and uploaded.

    More frames over the same walk is a faster machine, and the work of
    choosing the clumps follows the distance, not the frame rate.
    """
    def prepare(frames):
        def walk():
            cover, rung = _walking_cover()
            for x in np.linspace(0.0, 20.0, frames):
                cover.update((float(x), 0.0, 0.0))
            return rung.clumps_near.handed + rung.clumps_far.handed
        return walk
    check_scaling(prepare, n=100, most=1.5, measure='count')


@pytest.mark.serial
def test_a_walk_costs_what_the_cover_is_dense():
    def prepare(tenths):
        def walk():
            cover, _rung = _walking_cover(density=tenths / 10.0)
            for x in np.linspace(0.0, 20.0, 60):
                cover.update((float(x), 0.0, 0.0))
        return walk
    check_scaling(prepare, n=2, most=6.0, repeat=3)
