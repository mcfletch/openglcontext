"""What zones give one draw, one camera and one listener -- with no GL."""
import tracemalloc
import numpy as np
import pytest

from OpenGLContext.passes import zonelayers
from OpenGLContext.passes.zonelayers import (
    MAX_ZONE_LAYERS, NO_ENVIRONMENT, SCENE_PROBE, environment_layers, lights_off,
)
from OpenGLContext.passes.zoneprobes import CaptureSchedule
from OpenGLContext.scenegraph.basenodes import (
    PointLight, Zone, ZoneAudio, ZoneEnvironment, ZoneLights, ZoneReverb,
)
from OpenGLContext.scenegraph.zone import AUDIO, placed_zones


def translated(x, y=0.0, z=0.0):
    matrix = np.identity(4)
    matrix[3, :3] = (x, y, z)
    return matrix


def place(*pairs):
    """Zones placed from ``(zone, (x, y, z))`` pairs."""
    return placed_zones([(zone, translated(*where)) for zone, where in pairs])


def room(size=10.0, blend=0.0, priority=0, **settings):
    return Zone(size=(size, size, size), blend=blend, priority=priority,
                settings=list(settings.values()))


def scene_probe(_zone):
    return SCENE_PROBE


BOX = ((-1, -1, -1), (1, 1, 1))


class TestEnvironmentLayers:
    def test_no_zone_reaches_an_object_far_away(self):
        zones = place((room(environment=ZoneEnvironment(intensity=0.1)), (50, 0, 0)))
        assert environment_layers(zones, *BOX, scene_probe) is None

    def test_an_object_inside_takes_the_zone_as_a_constant(self):
        zones = place((room(environment=ZoneEnvironment(intensity=0.1)), (0, 0, 0)))
        pack = environment_layers(zones, *BOX, scene_probe)
        assert pack.count == 1
        assert pack.kinds[0] == 0
        assert pack.light[0][0] == pytest.approx(0.1)
        assert pack.light[0][2] == SCENE_PROBE

    def test_an_object_across_the_edge_is_weighted_per_fragment(self):
        zones = place((room(blend=1.0, environment=ZoneEnvironment(intensity=0.1)),
                       (0, 0, 0)))
        pack = environment_layers(zones, (4, -1, -1), (6, 1, 1), scene_probe)
        assert pack.count == 1 and pack.kinds[0] == 1           # a box
        assert pack.shape[0][:3] == pytest.approx((5.0, 5.0, 5.0))
        assert pack.light[0][1] == pytest.approx(1.0)

    def test_the_matrix_takes_a_world_point_into_the_shape(self):
        zones = place((room(environment=ZoneEnvironment()), (7, 0, 0)))
        pack = environment_layers(zones, (4, -1, -1), (14, 1, 1), scene_probe)
        world = np.array([7.0, 0.0, 0.0, 1.0])
        assert (world @ pack.to_local[0].astype('d'))[:3] == pytest.approx((0, 0, 0))

    def test_zones_under_the_one_an_object_is_inside_are_dropped(self):
        big = room(size=100.0, environment=ZoneEnvironment(intensity=0.5))
        small = room(size=10.0, environment=ZoneEnvironment(intensity=0.1))
        pack = environment_layers(place((big, (0, 0, 0)), (small, (0, 0, 0))),
                                  *BOX, scene_probe)
        assert pack.count == 1
        assert pack.light[0][0] == pytest.approx(0.1)

    def test_a_crossed_zone_stays_over_the_one_the_object_is_in(self):
        big = room(size=100.0, environment=ZoneEnvironment(intensity=0.5))
        small = room(size=10.0, environment=ZoneEnvironment(intensity=0.1))
        pack = environment_layers(place((big, (0, 0, 0)), (small, (0, 0, 0))),
                                  (4, -1, -1), (6, 1, 1), scene_probe)
        assert pack.count == 2
        assert list(pack.kinds[:2]) == [0, 1]
        assert pack.light[:2, 0] == pytest.approx((0.5, 0.1))

    def test_a_disabled_environment_has_none(self):
        zones = place((room(environment=ZoneEnvironment(enabled=False)), (0, 0, 0)))
        pack = environment_layers(zones, *BOX, scene_probe)
        assert pack.light[0][2] == NO_ENVIRONMENT

    def test_the_probe_layer_comes_from_the_caller(self):
        zones = place((room(environment=ZoneEnvironment(capture=True)), (0, 0, 0)))
        pack = environment_layers(zones, *BOX, lambda _zone: 3.0)
        assert pack.light[0][2] == 3.0

    def test_too_many_crossed_zones_keep_the_nearest(self):
        pairs = [(room(size=2.0, environment=ZoneEnvironment(intensity=0.1 * i)),
                  (x, 0, 0)) for i, x in enumerate(range(0, 12, 2))]
        warned = []
        pack = environment_layers(place(*pairs), (-5, -5, -5), (15, 5, 5),
                                  scene_probe, camera=(0, 0, 0), warn=warned.append)
        assert pack.count == MAX_ZONE_LAYERS
        assert pack.limited and warned
        kept = sorted(float(v) for v in pack.shape[:pack.count, 0])
        assert kept == [1.0] * MAX_ZONE_LAYERS

    def test_with_no_zone_it_is_inside_every_layer_goes_to_the_nearest(self):
        pairs = [(room(size=2.0, environment=ZoneEnvironment(intensity=0.1 * (i + 1))),
                  (x, 0, 0)) for i, x in enumerate(range(0, 12, 2))]
        warned = []
        pack = environment_layers(place(*pairs), (-5, -5, -5), (15, 5, 5),
                                  scene_probe, camera=(12, 0, 0), warn=warned.append)
        intensities = sorted(round(float(v), 3) for v in pack.light[:pack.count, 0])
        assert intensities == [0.3, 0.4, 0.5, 0.6]
        assert warned == ['an object crosses 6 zones; the 4 nearest the camera are kept']

    def test_the_zone_an_object_is_inside_stays_however_far(self):
        pairs = [(room(size=40.0, environment=ZoneEnvironment(intensity=0.05)), (0, 0, 0))]
        pairs += [(room(size=2.0, priority=1,
                        environment=ZoneEnvironment(intensity=0.1 * (i + 1))),
                   (x, 0, 0)) for i, x in enumerate(range(0, 12, 2))]
        warned = []
        pack = environment_layers(place(*pairs), (-5, -5, -5), (15, 5, 5),
                                  scene_probe, camera=(12, 0, 0), warn=warned.append)
        assert pack.kinds[0] == 0 and pack.light[0][0] == pytest.approx(0.05)
        assert sorted(round(float(v), 3) for v in pack.light[1:pack.count, 0]) == \
            [0.4, 0.5, 0.6]
        assert warned == ['an object crosses 6 zones; the 3 nearest the camera are kept']

    def test_equal_packs_compare_equal(self):
        zones = place((room(environment=ZoneEnvironment(intensity=0.1)), (0, 0, 0)))
        one = environment_layers(zones, *BOX, scene_probe)
        two = environment_layers(zones, (-2, -2, -2), (2, 2, 2), scene_probe)
        assert one.key == two.key


class TestLightsOff:
    def test_a_zone_light_is_off_outside_its_zone(self):
        lamp, sun = PointLight(), PointLight()
        zones = place((room(lights=ZoneLights(lights=[lamp])), (0, 0, 0)))
        controlled = zonelayers.controlled_lights(zones)
        inside = lights_off(zones, *BOX, [sun, lamp], controlled)
        outside = lights_off(zones, (50, 0, 0), (51, 1, 1), [sun, lamp], controlled)
        assert inside == 0
        assert outside == 0b10

    def test_a_zone_that_switches_lights_off_darkens_what_is_inside(self):
        sun = PointLight()
        zones = place((room(lights=ZoneLights(enabled=False)), (0, 0, 0)))
        controlled = zonelayers.controlled_lights(zones)
        assert lights_off(zones, *BOX, [sun], controlled) == 0b1
        assert lights_off(zones, (4, -1, -1), (6, 1, 1), [sun], controlled) == 0

    def test_a_light_named_by_a_zone_over_a_dark_one_stays_on(self):
        lamp, sun = PointLight(), PointLight()
        dark = room(size=100.0, lights=ZoneLights(enabled=False))
        lit = room(size=10.0, lights=ZoneLights(lights=[lamp]))
        zones = place((dark, (0, 0, 0)), (lit, (0, 0, 0)))
        controlled = zonelayers.controlled_lights(zones)
        assert lights_off(zones, *BOX, [sun, lamp], controlled) == 0


class TestTheCamera:
    def test_an_emitter_is_heard_inside_and_fades_over_the_blend(self):
        zones = place((room(blend=2.0, audio=ZoneAudio()), (0, 0, 0)))

        def names(_setting):
            return ['bird']
        inside = zonelayers.camera_shares(zones, (0, 0, 0), AUDIO, names)
        edge = zonelayers.camera_shares(zones, (6, 0, 0), AUDIO, names)
        away = zonelayers.camera_shares(zones, (20, 0, 0), AUDIO, names)
        assert inside['bird'] == 1.0
        assert 0.0 < edge['bird'] < 1.0
        assert away.get('bird', 0.0) == 0.0

    def test_the_reverb_is_the_zones_and_none_outside(self):
        zones = place((room(blend=2.0, reverb=ZoneReverb(level=0.6, decay=2.0)),
                       (0, 0, 0)))
        inside = zonelayers.reverb_at(zones, (0, 0, 0))
        edge = zonelayers.reverb_at(zones, (6, 0, 0))
        away = zonelayers.reverb_at(zones, (20, 0, 0))
        assert (inside.level, inside.decay) == pytest.approx((0.6, 2.0))
        assert 0.0 < edge.level < 0.6 and edge.decay == pytest.approx(2.0)
        assert away.level == 0.0

    def test_two_reverbs_meet_without_a_jump(self):
        hall = room(size=100.0, reverb=ZoneReverb(level=0.2, decay=1.0))
        bore = room(size=10.0, blend=4.0, reverb=ZoneReverb(level=0.6, decay=3.0))
        zones = place((hall, (0, 0, 0)), (bore, (0, 0, 0)))
        middle = zonelayers.reverb_at(zones, (7, 0, 0))
        assert 0.2 < middle.level < 0.6 and 1.0 < middle.decay < 3.0


class TestCaptureSchedule:
    def test_a_zone_is_captured_as_many_times_as_it_bounces(self):
        schedule = CaptureSchedule(bounces=2)
        assert schedule.request('naos') and not schedule.request('naos')
        assert schedule.layer('naos') is None
        for _capture in range(2):
            assert schedule.next(lambda _key: 0.0) == 'naos'
            assert schedule.faces('naos', 6) == [0, 1, 2, 3, 4, 5]
            assert schedule.drawn('naos', 6)
            schedule.finished('naos')
            assert schedule.layer('naos') == 1
        assert schedule.next(lambda _key: 0.0) is None

    def test_the_camera_inside_asks_for_one_more(self):
        schedule = CaptureSchedule(bounces=1)
        schedule.request('naos')
        schedule.drawn('naos', 6)
        schedule.finished('naos')
        schedule.camera_inside('naos')
        schedule.camera_inside('naos')
        assert schedule.next(lambda _key: 0.0) == 'naos'
        schedule.drawn('naos', 6)
        schedule.finished('naos')
        assert schedule.next(lambda _key: 0.0) is None

    def test_the_nearest_goes_first_and_a_started_one_is_finished(self):
        schedule = CaptureSchedule()
        for key in ('far', 'near'):
            schedule.request(key)
        distance = {'far': 100.0, 'near': 1.0}.get
        assert schedule.next(distance) == 'near'
        assert schedule.faces('near', 2) == [0, 1]
        assert not schedule.drawn('near', 2)
        schedule.request('nearer')
        assert schedule.next(lambda key: 0.0 if key == 'nearer' else 5.0) == 'near'
        assert schedule.faces('near', 2) == [2, 3]

    def test_layers_are_reused_once_a_zone_is_gone(self):
        schedule = CaptureSchedule()
        schedule.request('a')
        schedule.request('b')
        assert schedule.layers == 3
        schedule.keep(['b'])
        schedule.request('c')
        assert schedule.layers == 3
        schedule.drawn('c', 6)
        schedule.finished('c')
        assert schedule.layer('c') == 1

    def test_lost_layers_are_captured_again(self):
        schedule = CaptureSchedule(bounces=1)
        schedule.request('a')
        schedule.drawn('a', 6)
        schedule.finished('a')
        schedule.lost()
        assert schedule.layer('a') is None
        assert schedule.waiting


class TestTheTable:
    def test_it_keeps_exactly_the_zones_classification_does_not_rule_out(self):
        rng = np.random.default_rng(4)
        pairs = [(room(size=float(rng.uniform(2, 20)), blend=float(rng.uniform(0, 5)),
                       environment=ZoneEnvironment()),
                  tuple(rng.uniform(-60, 60, 3))) for _ in range(40)]
        pairs += [(Zone(shapeType='sphere', radius=float(rng.uniform(2, 10)),
                        settings=[ZoneEnvironment()]),
                   tuple(rng.uniform(-60, 60, 3))) for _ in range(10)]
        zones = place(*pairs)
        table = zonelayers.ZoneTable(zones)
        for _ in range(20):
            low = rng.uniform(-50, 50, 3)
            high = low + rng.uniform(0.5, 30, 3)
            kept = {id(zone): inside for zone, inside in table.classify(low, high)}
            wanted = {id(zone): where == 'inside' for zone in zones
                      for where in (zone.shape.classify(low, high, zone.blend),)
                      if where != 'outside'}
            assert kept == wanted
            near = table.nearness(low)
            for zone in zones:
                assert near[zone] == pytest.approx(float(zone.shape.distance(low)))

    def test_layers_through_the_table_are_the_same(self):
        zones = place((room(environment=ZoneEnvironment(intensity=0.3)), (0, 0, 0)),
                      (room(size=4.0, environment=ZoneEnvironment()), (40, 0, 0)))
        table = zonelayers.ZoneTable(zones)
        direct = environment_layers(zones, *BOX, scene_probe)
        tabled = environment_layers(zones, *BOX, scene_probe, table=table)
        assert direct.key == tabled.key


def test_the_table_weighs_every_zone_at_a_point_as_each_would():
    rng = np.random.default_rng(9)
    pairs = [(room(size=float(rng.uniform(2, 20)), blend=float(rng.choice([0.0, 3.0])),
                   environment=ZoneEnvironment()), tuple(rng.uniform(-30, 30, 3)))
             for _ in range(30)]
    zones = place(*pairs)
    table = zonelayers.ZoneTable(zones)
    for _ in range(10):
        point = rng.uniform(-30, 30, 3)
        found = zonelayers.point_weights(table, point)
        for zone in zones:
            assert found[zone] == pytest.approx(zone.weight(point), abs=1e-9)


def _spread(rng, count=60, across=2000.0):
    """Turned, scaled zones along a long stretch of world, as a road's are."""
    placed = []
    for _ in range(count):
        angle = float(rng.uniform(0, 2 * np.pi))
        matrix = np.identity(4)
        matrix[0, 0] = matrix[2, 2] = np.cos(angle)
        matrix[0, 2], matrix[2, 0] = np.sin(angle), -np.sin(angle)
        matrix[:3, :3] *= float(rng.uniform(0.5, 2.0))
        matrix[3, :3] = (rng.uniform(-across / 2, across / 2), rng.uniform(-5, 5),
                         rng.uniform(-across / 2, across / 2))
        zone = Zone(size=tuple(rng.uniform(4, 80, 3)), blend=float(rng.uniform(0, 25)),
                    settings=[ZoneEnvironment()])
        placed.append((zone, matrix))
    return placed_zones(placed)


class TestManyBoxesAtOnce:
    def test_the_answer_does_not_depend_on_how_many_are_taken_at_a_time(self):
        rng = np.random.default_rng(31)
        zones = _spread(rng)
        whole = zonelayers.ZoneTable(zones)
        pieces = zonelayers.ZoneTable(zones)
        pieces.chunk = 7
        lows = rng.uniform(-900, 900, (100, 3)) * (1, 0.01, 1)
        highs = lows + rng.uniform(0.5, 40, (100, 3))

        def ids(found):
            return [[(id(z), inside) for z, inside in row] for row in found]

        assert ids(whole.classify_many(lows, highs)) == ids(pieces.classify_many(lows, highs))

    def test_a_first_frame_of_many_objects_over_many_zones_stays_small(self):
        """Twenty thousand boxes over fifty-six zones along a road, in no order."""
        rng = np.random.default_rng(32)
        placed = [(room(size=20.0, blend=5.0, environment=ZoneEnvironment()), (x, 0, 0))
                  for x in np.linspace(-1000, 1000, 56)]
        table = zonelayers.ZoneTable(place(*placed))
        lows = rng.uniform(-1000, 1000, (20000, 3)) * (1, 0.005, 0.005)
        highs = lows + 2.0
        tracemalloc.start()
        try:
            table.classify_many(lows, highs)
            _now, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 64 * 1024 * 1024, peak


class TestObjectBoxes:
    def test_the_objects_a_changed_region_reaches_are_found(self):
        boxes = zonelayers.ObjectBoxes(capacity=2)
        rows = {name: boxes.place(None, name, (x, 0, 0), (x + 1, 1, 1))
                for name, x in (('a', 0.0), ('b', 10.0), ('c', 20.0))}
        assert len(boxes) == 3
        assert sorted(boxes.overlapping((9.5, 0, 0), (21, 1, 1))) == ['b', 'c']
        boxes.drop(rows['b'])
        assert boxes.overlapping((9.5, 0, 0), (21, 1, 1)) == ['c']
        assert boxes.place(None, 'd', (5, 0, 0), (6, 1, 1)) == rows['b']
        boxes.place(rows['a'], 'a', (100, 0, 0), (101, 1, 1))
        assert boxes.overlapping((-1, -1, -1), (2, 2, 2)) == []
        boxes.clear()
        assert len(boxes) == 0 and boxes.overlapping((-1e9,) * 3, (1e9,) * 3) == []


class TestTheTableAsksOnlyTheZonesNearby:
    """A moving object is near a few of a world's zones; the table's detailed
    tests are made against those, and the answers are every zone's."""

    def test_many_boxes_are_classified_as_each_zone_would(self):
        rng = np.random.default_rng(21)
        zones = _spread(rng)
        table = zonelayers.ZoneTable(zones)
        for _ in range(15):
            centre = rng.uniform(-900, 900, 3) * (1, 0.01, 1)
            lows = centre + rng.uniform(-8, 8, (6, 3))
            highs = lows + rng.uniform(0.5, 6, (6, 3))
            for low, high, found in zip(lows, highs, table.classify_many(lows, highs)):
                kept = {id(zone): inside for zone, inside in found}
                wanted = {id(zone): where == 'inside' for zone in zones
                          for where in (zone.shape.classify(low, high, zone.blend),)
                          if where != 'outside'}
                assert kept == wanted

    def test_a_box_near_a_zone_is_tested_against_it(self):
        zones = _spread(np.random.default_rng(22))
        table = zonelayers.ZoneTable(zones)
        some = zones[7]
        at = np.asarray(some.shape.centre, 'd')
        found = table.classify_many([at - 0.5], [at + 0.5])[0]
        assert (some, True) in found

    def test_far_zones_are_not_asked(self):
        zones = _spread(np.random.default_rng(23))
        table = zonelayers.ZoneTable(zones)
        near = table.near([-5.0, -5.0, -5.0], [5.0, 5.0, 5.0])
        assert len(near) < len(zones) / 4

    def test_slack_never_overstates_the_room(self):
        rng = np.random.default_rng(24)
        zones = _spread(rng)
        table = zonelayers.ZoneTable(zones)
        everything = zonelayers.ZoneTable(zones)
        everything.slack_reach = np.inf
        centres = rng.uniform(-900, 900, (200, 3)) * (1, 0.01, 1)
        radii = rng.uniform(0.2, 4.0, 200)
        found = table.sphere_slack(centres, radii)
        exact = everything.sphere_slack(centres, radii)
        assert np.all(found <= exact + 1e-9)
        close = exact < table.slack_reach - radii
        assert close.any()
        assert np.allclose(found[close], exact[close])
