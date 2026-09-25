"""Zones in the PBR pass: the shader contract, the pass's bookkeeping, and renders.

The shader and the pass meet at a handful of uniforms, so the contract is
checked from the source. The pass's decisions -- what a draw is handed, when it
uploads, what the camera hides, which mirrors draw -- are checked on a pass
built without GL. The renders (``tests/helpers/_zone_capture.py``) show the
whole of it: a floor crossing a zone's edge, a sphere inside it and one outside.
"""
import json
import os
import re
import subprocess
import sys

import numpy as np
import pytest

from OpenGLContext.passes.shaderpass import SHADER_DIR
from OpenGLContext.passes.zonepass import ZonesMixin
from OpenGLContext.scenegraph.basenodes import (
    AudioEmitter, PointLight, Transform, Zone, ZoneAudio, ZoneEnvironment,
    ZoneGravity, ZoneLights, ZoneMirrors, ZoneReverb, ZoneVisibility,
)
from OpenGLContext.scenegraph.zone import placed_zones
from OpenGLContext.testing.paths import tests_root

TESTS_DIR = str(tests_root(__file__))
CAPTURE = os.path.join(TESTS_DIR, 'helpers', '_zone_capture.py')
COST = os.path.join(TESTS_DIR, 'helpers', '_zone_cost_harness.py')


def _source(name):
    with open(os.path.join(SHADER_DIR, name)) as handle:
        return handle.read()


class TestShaderSource:
    def test_the_fragment_shader_reads_the_zones(self):
        source = _source('pbr.frag')
        assert '#include "_zone_inc.glsl"' in source
        assert re.search(r'zoneShares\(\s*\(eyeToWorld \* vec4\(vPosition', source)

    def test_every_environment_term_goes_through_the_zones(self):
        """A sample of the probe outside the two helpers would ignore a zone."""
        source = _source('pbr.frag')
        body = source[source.index('vec3 envIrradiance('):]
        direct = re.findall(r'texture(?:Lod)?\(\s*(?:irradianceMap|prefilterMap)', body)
        assert len(direct) == 0, 'the probe is sampled outside the helpers'
        assert 'probeIrradiance(d, 0.0) * zoneScene' in source
        assert 'probeRadiance(d, lod, 0.0) * zoneScene' in source

    def test_lightmaps_and_the_light_grid_are_not_scaled(self):
        source = _source('pbr.frag')
        assert 'ambDiffuse += lightmap * albedo' in source
        assert 'ambDiffuse += gridLight * albedo' in source

    def test_a_zone_can_switch_a_light_off_for_a_draw(self):
        source = _source('pbr.frag')
        assert 'uniform int lightsOff;' in source
        assert re.search(r'if \(\(lightsOff & \(1 << i\)\) != 0\) continue;', source)

    def test_the_include_and_the_arithmetic_agree_on_the_shapes(self):
        from OpenGLContext.scenegraph import zones
        source = _source('_zone_inc.glsl')
        for kind in zones.SHAPES + (zones.ELLIPSOID,):
            assert 'kind == %d' % zones.shader_kind(kind) in source or \
                zones.shader_kind(kind) == 5      # the fall-through: a cylinder

    def test_the_layer_count_matches(self):
        from OpenGLContext.passes.zonelayers import MAX_ZONE_LAYERS
        assert '#define MAX_ZONE_LAYERS %d' % MAX_ZONE_LAYERS in _source('_zone_inc.glsl')


class TestTheProgramAPI:
    def _program(self, monkeypatch):
        from OpenGLContext.passes import pbrpass
        program = pbrpass.PBRShaderProgram.__new__(pbrpass.PBRShaderProgram)
        program.program = 7
        calls = []
        program._set_uniform1i = lambda name, value, prog=None: calls.append((name, int(value)))
        program._get_location = lambda name, prog=None: {'zoneKind': 1, 'zoneToLocal': 2,
                                                         'zoneShape': 3, 'zoneLight': 4}[name]
        monkeypatch.setattr(pbrpass, 'glUniform1iv', lambda loc, n, v: calls.append(('1iv', loc, n)))
        monkeypatch.setattr(pbrpass, 'glUniform4fv', lambda loc, n, v: calls.append(('4fv', loc, n)))
        monkeypatch.setattr(pbrpass, 'glUniformMatrix4fv',
                            lambda loc, n, t, v: calls.append(('m4', loc, n, t)))
        return program, calls

    def test_no_zones_uploads_one_integer(self, monkeypatch):
        program, calls = self._program(monkeypatch)
        program.set_zones(None)
        assert calls == [('zoneLayers', 0)]

    def test_a_pack_uploads_every_array_then_the_count(self, monkeypatch):
        from OpenGLContext.passes.zonelayers import MAX_ZONE_LAYERS, environment_layers
        program, calls = self._program(monkeypatch)
        zones = placed_zones([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment()]),
                               np.identity(4))])
        pack = environment_layers(zones, (-1, -1, -1), (1, 1, 1), lambda z: -1.0)
        program.set_zones(pack)
        assert calls[-1] == ('zoneLayers', 1)
        assert ('1iv', 1, MAX_ZONE_LAYERS) in calls
        assert ('m4', 2, MAX_ZONE_LAYERS, False) in calls
        assert ('4fv', 3, MAX_ZONE_LAYERS) in calls and ('4fv', 4, MAX_ZONE_LAYERS) in calls

    def test_the_light_mask(self, monkeypatch):
        program, calls = self._program(monkeypatch)
        program.set_lights_off(0b101)
        assert calls == [('lightsOff', 5)]


class FakePath(list):
    """A node path: the nodes from the root, and the world matrix at its end."""

    def __init__(self, nodes, matrix):
        super().__init__(nodes)
        self.matrix = matrix
        self.broken = False

    def transformMatrix(self):
        return self.matrix


class FakeShader:
    def __init__(self):
        self.zones, self.masks = [], []

    def set_zones(self, pack=None, program=None):
        self.zones.append(pack)

    def set_lights_off(self, mask=0, program=None):
        self.masks.append(mask)


class Box:
    """A bounding volume of eight corners about the origin.

    One object for each size, as a node's cached volume is one object until
    its bounds change.
    """

    _made: dict = {}

    def __new__(cls, half):
        found = cls._made.get(half)
        if found is None:
            found = cls._made[half] = super().__new__(cls)
            found.half = half
        return found

    def getPoints(self):
        h = self.half
        return np.array([(x, y, z, 1.0) for x in (-h, h) for y in (-h, h)
                         for z in (-h, h)])


class ZonedPass(ZonesMixin):
    """The mixin on its own, with what it reads from a real pass stubbed in."""

    def __init__(self, zones):
        self.paths = {Zone: [FakePath([zone], matrix) for zone, matrix in zones]}
        self.shader_program = FakeShader()
        self.activeFrame = None
        self.boundLights = []


def at(x, y=0.0, z=0.0):
    matrix = np.identity(4)
    matrix[3, :3] = (x, y, z)
    return matrix


class TestThePass:
    def test_a_scene_with_no_zones_does_nothing_per_draw(self):
        zoned = ZonedPass([])
        zoned.placeZones()
        zoned.applyZones(zoned.shader_program, object(), at(0), Box(1))
        assert zoned.shader_program.zones == []

    def test_a_draw_is_handed_its_zones_once_for_a_run_of_alike_draws(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment(intensity=0.2)]),
                            at(0))])
        zoned.placeZones()
        zoned.setupZones(np.identity(4))
        shader = zoned.shader_program
        shader.zones.clear()
        for index in range(3):
            zoned.applyZones(shader, ('path', index), at(0), Box(1))
        assert len(shader.zones) == 1
        assert shader.zones[0].light[0][0] == pytest.approx(0.2)
        zoned.applyZones(shader, 'outside', at(50), Box(1))
        assert shader.zones[-1] is None

    def test_what_an_object_gets_is_kept_until_it_moves(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment()]), at(0))])
        zoned.placeZones()
        where = at(0)
        path = ('box',)
        pack, _mask = zoned.zoneState(path, where, Box(1))
        assert zoned.zoneState(path, where, Box(1))[0] is pack
        assert zoned._zoneObjects[id(path)].matrix is where
        moved = at(50)
        assert zoned.zoneState(path, moved, Box(1)) == (None, 0)

    def test_the_light_mask_follows_the_zone(self):
        lamp = PointLight()
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneLights(lights=[lamp])]),
                            at(0))])
        zoned.boundLights = [PointLight(), lamp]
        zoned.placeZones()
        zoned.setupZones(np.identity(4))
        shader = zoned.shader_program
        zoned.applyZones(shader, 'in', at(0), Box(1))
        zoned.applyZones(shader, 'out', at(50), Box(1))
        assert shader.masks[-1] == 0b10

    def test_a_zone_moving_is_noticed(self):
        zone = Zone(size=(10, 10, 10), settings=[ZoneEnvironment()])
        zoned = ZonedPass([(zone, at(0))])
        placed = zoned.placeZones()
        assert zoned.placeZones()[0] is placed[0]
        zoned.paths[Zone][0].matrix = at(5)
        assert zoned.placeZones()[0] is not placed[0]


    def test_a_zone_of_no_known_shape_is_left_out_and_reported_once(self, caplog):
        zoned = ZonedPass([(Zone(shapeType='Box', settings=[ZoneEnvironment()]), at(0))])
        with caplog.at_level('WARNING', logger='OpenGLContext.scenegraph.zone'):
            assert zoned.placeZones() == []
            assert zoned.placeZones() == []
        assert len([r for r in caplog.records if "'Box'" in r.getMessage()]) == 1


class TestTheCamera:
    def test_a_shown_node_is_drawn_only_from_inside(self):
        secret = Transform()
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[
            ZoneVisibility(nodes=[secret], visible=True)]), at(0))])
        zoned.placeZones()
        assert id(secret) not in zoned.zoneHiddenAt(np.zeros(3))
        assert id(secret) in zoned.zoneHiddenAt(np.array([50.0, 0, 0]))

    def test_a_hidden_node_is_hidden_only_from_inside(self):
        clutter = Transform()
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[
            ZoneVisibility(nodes=[clutter], visible=False)]), at(0))])
        zoned.placeZones()
        assert id(clutter) in zoned.zoneHiddenAt(np.zeros(3))
        assert id(clutter) not in zoned.zoneHiddenAt(np.array([50.0, 0, 0]))

    def test_a_named_mirror_draws_only_from_inside(self):
        mirror = Transform()
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[
            ZoneMirrors(nodes=[mirror])]), at(0))])
        zoned.placeZones()
        record = (None, None, None, None, [mirror], None)
        assert zoned.mirrorsZoned()
        assert zoned.mirrorAllowed(record, np.zeros(3))
        assert not zoned.mirrorAllowed(record, np.array([50.0, 0, 0]))

    def test_a_zone_can_stop_every_other_mirror(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[
            ZoneMirrors(enabled=False)]), at(0))])
        zoned.placeZones()
        record = (None, None, None, None, [Transform()], None)
        assert not zoned.mirrorAllowed(record, np.zeros(3))
        assert zoned.mirrorAllowed(record, np.array([50.0, 0, 0]))


class FakeEngine:
    """An engine with a reverb and nothing else."""

    def __init__(self, level=0.0, decay=1.2, damping=0.4):
        class Reverb:
            pass
        self.reverb = Reverb()
        self.reverb.level, self.reverb.decay, self.reverb.damping = level, decay, damping


class TestAudio:
    def test_zone_emitters_are_heard_inside_and_the_reverb_is_the_zones(self):
        from OpenGLContext.audio.areas import apply_zones
        birds, music = AudioEmitter(type='global'), AudioEmitter(type='global')
        zones = placed_zones([(Zone(size=(10, 10, 10), blend=2.0, settings=[
            ZoneAudio(emitters=[birds]), ZoneReverb(level=0.5, decay=2.0)]), at(0))])

        engine = FakeEngine()
        apply_zones(engine, [birds, music], zones, (0, 0, 0))
        assert birds.zoneGain == 1.0 and music.zoneGain == 1.0
        assert engine.reverb.level == pytest.approx(0.5)
        apply_zones(engine, [birds, music], zones, (6, 0, 0))
        assert 0.0 < birds.zoneGain < 1.0
        apply_zones(engine, [birds, music], zones, (50, 0, 0))
        assert birds.zoneGain == 0.0 and music.zoneGain == 1.0
        assert engine.reverb.level == 0.0

    def test_zones_with_no_reverb_leave_the_applications_alone(self):
        from OpenGLContext.audio.areas import apply_zones
        zones = placed_zones([(Zone(size=(10, 10, 10), settings=[
            ZoneEnvironment(intensity=0.2)]), at(0))])
        engine = FakeEngine(level=0.3, decay=2.5)
        for where in ((0, 0, 0), (50, 0, 0)):
            apply_zones(engine, [], zones, where)
            assert (engine.reverb.level, engine.reverb.decay) == (0.3, 2.5)

    def test_a_reverb_zone_is_laid_over_the_applications_reverb(self):
        from OpenGLContext.audio.areas import apply_zones
        zones = placed_zones([(Zone(size=(10, 10, 10), blend=2.0, settings=[
            ZoneReverb(level=0.6, decay=3.0)]), at(0))])
        engine = FakeEngine(level=0.3, decay=1.0)
        apply_zones(engine, [], zones, (0, 0, 0))
        assert (engine.reverb.level, engine.reverb.decay) == pytest.approx((0.6, 3.0))
        apply_zones(engine, [], zones, (6, 0, 0))
        assert 0.3 < engine.reverb.level < 0.6 and 1.0 < engine.reverb.decay < 3.0
        apply_zones(engine, [], zones, (50, 0, 0))
        assert (engine.reverb.level, engine.reverb.decay) == pytest.approx((0.3, 1.0))

    def test_the_application_changing_its_reverb_is_kept(self):
        from OpenGLContext.audio.areas import apply_zones
        zones = placed_zones([(Zone(size=(10, 10, 10), settings=[
            ZoneReverb(level=0.6)]), at(0))])
        engine = FakeEngine(level=0.1)
        apply_zones(engine, [], zones, (50, 0, 0))
        engine.reverb.level = 0.45
        apply_zones(engine, [], zones, (50, 0, 0))
        assert engine.reverb.level == pytest.approx(0.45)
        apply_zones(engine, [], zones, (0, 0, 0))
        assert engine.reverb.level == pytest.approx(0.6)
        apply_zones(engine, [], (), (0, 0, 0))
        assert engine.reverb.level == pytest.approx(0.45)

    def test_the_zone_gain_scales_the_record(self):
        emitter = AudioEmitter(gain=0.8)
        emitter.zoneGain = 0.5
        assert emitter.record().gain == pytest.approx(0.4)


class TestGravity:
    def test_a_zone_is_a_gravity_volume_over_its_shape(self):
        from OpenGLContext.physics.zones import gravity_volumes, scene_zones
        turned = Transform(translation=(0, 10, 0), rotation=(0, 0, 1, np.pi), children=[
            Zone(size=(4, 4, 4), priority=3, settings=[
                ZoneGravity(gravity=2.0, direction=(0, -1, 0), replace=True)])])
        (volume,) = gravity_volumes(scene_zones(Transform(children=[turned])))
        assert volume.priority == 3
        assert volume.contains(np.array([0.0, 11.0, 0.0]))
        assert not volume.contains(np.array([0.0, 0.0, 0.0]))
        assert volume.field.direction == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)
        assert volume.field.replace

    def test_a_collision_world_carries_the_volumes(self):
        from OpenGLContext.physics.gltf_world import collision_world_from_scene
        scene = Transform(children=[Zone(size=(4, 4, 4), settings=[ZoneGravity()])])
        world, _bounds = collision_world_from_scene(scene)
        assert len(world.gravity_volumes) == 1


# -- renders ------------------------------------------------------------------

def _render(tmp_path_factory, mode):
    out = str(tmp_path_factory.mktemp('zones') / ('%s.png' % mode))
    done = subprocess.run([sys.executable, CAPTURE, out, mode], capture_output=True,
                          text=True, timeout=300)
    if not os.path.exists(out):
        pytest.skip('no zone render (%s): %s' % (mode, done.stderr[-500:]))
    from PIL import Image
    return np.asarray(Image.open(out).convert('RGB'), dtype='d')


@pytest.fixture(scope='module')
def renders(tmp_path_factory):
    return {mode: _render(tmp_path_factory, mode)
            for mode in ('none', 'dim', 'capture', 'lights', 'nolights', 'imagelight')}


def _regions(image):
    """The mean of the left third and the right third, over the floor's rows."""
    height, width, _ = image.shape
    band = image[int(height * 0.45):int(height * 0.75)]
    return band[:, :width // 3].mean(axis=(0, 1)), band[:, 2 * width // 3:].mean(axis=(0, 1))


@pytest.mark.slow
class TestRenders:
    def test_inside_the_dim_zone_is_darker_and_outside_is_not(self, renders):
        plain_left, plain_right = _regions(renders['none'])
        dim_left, dim_right = _regions(renders['dim'])
        assert dim_left.mean() < 0.5 * plain_left.mean()
        assert abs(dim_right.mean() - plain_right.mean()) < 3.0

    def test_a_captured_probe_lights_the_zone_by_what_it_sees(self, renders):
        """The room's walls see a black sky and almost no light, so its probe is dark."""
        plain_left, plain_right = _regions(renders['none'])
        captured_left, captured_right = _regions(renders['capture'])
        assert captured_left.mean() < 0.5 * plain_left.mean()
        assert abs(captured_right.mean() - plain_right.mean()) < 3.0

    def test_an_image_based_light_lights_the_zone(self, renders):
        _plain_left, plain_right = _regions(renders['none'])
        left, right = _regions(renders['imagelight'])
        assert left[0] > 1.5 * left[1] and left[0] > 1.5 * left[2]
        assert abs(right.mean() - plain_right.mean()) < 3.0

    def test_a_zone_light_lights_nothing_outside_its_zone(self, renders):
        _left, zoned_right = _regions(renders['lights'])
        _left, open_right = _regions(renders['nolights'])
        red = lambda rgb: rgb[0] - (rgb[1] + rgb[2]) / 2.0   # noqa: E731
        assert red(open_right) > red(zoned_right) + 1.0


@pytest.mark.serial
@pytest.mark.performance
def test_zones_cost_a_fill_bound_frame_little():
    """Four zones across every fragment of a full-window floor.

    Held to a generous ratio, since this has to pass on a slow machine too:
    what it is here to catch is the per-fragment test growing into a multiple
    of the frame.
    """
    def median(mode):
        done = subprocess.run([sys.executable, COST, '120', mode], capture_output=True,
                              text=True, timeout=600)
        if done.returncode == 3:
            pytest.skip('no usable GL context for the zone cost harness')
        assert done.returncode == 0, done.stderr[-2000:]
        line = [text for text in done.stdout.splitlines() if text.startswith('{')][-1]
        return json.loads(line)['median_ms']
    plain = min(median('plain') for _ in range(2))
    zoned = min(median('zones') for _ in range(2))
    assert zoned < plain * 1.6 + 0.5, (plain, zoned)


class TestManyZones:
    def test_an_object_crossing_too_many_is_chosen_again_only_as_the_camera_moves(self):
        pairs = [(Zone(size=(2, 2, 2), settings=[ZoneEnvironment(intensity=0.1 * i)]),
                  at(x)) for i, x in enumerate(range(0, 20, 2))]
        zoned = ZonedPass(pairs)
        zoned.placeZones()
        zoned.setupZones(np.identity(4))

        class Everything:
            def getPoints(self):
                return np.array([(x, y, z, 1.0) for x in (-100, 100)
                                 for y in (-100, 100) for z in (-100, 100)])
        path, where, everything = ('ground',), at(0), Everything()

        def reached():
            zoned.zoneState(path, where, everything)
            return zoned._zoneObjects[id(path)].reach

        first = reached()
        assert first.limited
        assert reached() is first

        def camera_at(x):
            moved = np.identity(4)
            moved[3, :3] = (x, 0.0, 0.0)
            zoned.setupZones(np.linalg.inv(moved))
        camera_at(3.0)
        assert reached() is first
        camera_at(100.0)
        assert reached() is not first

    def test_a_finished_capture_repacks_without_classifying_again(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment()]), at(0))])
        zoned.placeZones()
        layer = [-1.0]
        zoned.zoneProbeLayer = lambda zone: layer[0]
        path, where = ('box',), at(0)
        first, _mask = zoned.zoneState(path, where, Box(1))
        found = zoned._zoneObjects[id(path)].reach
        layer[0] = 2.0
        zoned._probeVersion += 1        # as a finished capture does
        second, _mask = zoned.zoneState(path, where, Box(1))
        assert zoned._zoneObjects[id(path)].reach is found
        assert second is not first and second.light[0][2] == 2.0


class TestMovingObjectsTogether:
    def test_the_objects_that_moved_are_classified_in_one_pass_as_each_would_be(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), blend=1.0,
                                 settings=[ZoneEnvironment(intensity=0.3)]), at(0)),
                           (Zone(size=(4, 4, 4), priority=1,
                                 settings=[ZoneEnvironment(intensity=0.1)]), at(20))])
        zoned.placeZones()
        records = [(None, None, at(x), Box(1), ('car', x), None)
                   for x in (0.0, 4.5, 20.0, 60.0, -30.0)]
        calls = []
        table = zoned._environmentTable
        real = table.classify_many
        table.classify_many = lambda *a: calls.append(1) or real(*a)
        zoned.refreshZones(records)
        assert calls == [1]
        zoned.refreshZones(records)
        assert calls == [1]
        together = [zoned._zoneObjects[id(r[4])].reach for r in records]
        for record, found in zip(records, together):
            alone = ZonedPass([(zone.zone, zone.matrix) for zone in zoned.zones])
            alone.placeZones()
            alone.refreshZones([record])
            one = alone._zoneObjects[id(record[4])].reach
            assert (None if one is None else [(id(z.zone), i) for z, i in one.stack]) == \
                (None if found is None else [(id(z.zone), i) for z, i in found.stack])


class TestSlack:
    def test_an_object_moving_within_its_slack_is_not_classified_again(self):
        zoned = ZonedPass([(Zone(size=(100, 100, 100), blend=2.0,
                                 settings=[ZoneEnvironment(intensity=0.3)]), at(0))])
        zoned.placeZones()
        path = ('car',)
        zoned.zoneState(path, at(0), Box(1))
        held = zoned._zoneObjects[id(path)]
        assert held.slack == pytest.approx(50.0 - 3 ** 0.5, abs=1e-6)
        zoned.zoneState(path, at(10), Box(1))
        assert zoned._zoneObjects[id(path)] is held
        zoned.zoneState(path, at(49.5), Box(1))
        assert zoned._zoneObjects[id(path)] is not held

    def test_an_object_across_an_edge_has_none(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment()]), at(0))])
        zoned.placeZones()
        path = ('car',)
        zoned.zoneState(path, at(5), Box(1))
        held = zoned._zoneObjects[id(path)]
        assert held.slack == 0.0
        zoned.zoneState(path, at(5.01), Box(1))
        assert zoned._zoneObjects[id(path)] is not held


class TestInstancedGroups:
    def test_a_group_is_classified_once_until_a_member_moves(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment(intensity=0.2)]),
                            at(0))])
        zoned.placeZones()
        zoned.setupZones(np.identity(4))
        members = [(None, None, at(x), Box(1), ('tree', x), None) for x in (-2.0, 0.0, 2.0)]
        calls = []
        real = zoned._classify
        zoned._classify = lambda items: calls.append(len(items)) or real(items)
        shader = zoned.shader_program
        zoned.applyZonesToGroup(shader, members, key='trees')
        zoned.applyZonesToGroup(shader, members, key='trees')
        assert calls == [1]
        assert shader.zones[-1].light[0][0] == pytest.approx(0.2)
        moved = list(members)
        moved[0] = (None, None, at(30.0), Box(1), ('tree', -2.0), None)
        zoned.applyZonesToGroup(shader, moved, key='trees')
        assert calls == [1, 1]
        assert shader.zones[-1].kinds[0] == 1        # the group now crosses the edge


class TestEditingAZone:
    """A zone's settings edited at run time reach what the pass already worked out."""

    def zoned(self, *settings):
        zone = Zone(size=(10, 10, 10), settings=list(settings))
        zoned = ZonedPass([(zone, at(0))])
        zoned.placeZones()
        zoned.setupZones(np.identity(4))
        return zone, zoned

    def pack(self, zoned, path=('box',), where=None):
        zoned.placeZones()
        return zoned.zoneState(path, at(0) if where is None else where, Box(1))

    def test_an_edited_intensity_reaches_an_object_already_classified(self):
        setting = ZoneEnvironment(intensity=0.2)
        _zone, zoned = self.zoned(setting)
        where = at(0)
        assert self.pack(zoned, where=where)[0].light[0][0] == pytest.approx(0.2)
        setting.intensity = 0.9
        assert self.pack(zoned, where=where)[0].light[0][0] == pytest.approx(0.9)

    def test_an_environment_switched_off_lights_nothing(self):
        setting = ZoneEnvironment(intensity=0.5)
        _zone, zoned = self.zoned(setting)
        where = at(0)
        self.pack(zoned, where=where)
        setting.enabled = False
        assert self.pack(zoned, where=where)[0].light[0][0] == 0.0

    def test_a_setting_added_to_a_placed_zone_reaches_what_is_inside(self):
        zone, zoned = self.zoned(ZoneEnvironment(intensity=0.5))
        zone.settings = []
        where = at(0)
        assert self.pack(zoned, where=where)[0] is None
        zone.settings = [ZoneEnvironment(intensity=0.3)]
        assert self.pack(zoned, where=where)[0].light[0][0] == pytest.approx(0.3)

    def test_a_setting_appended_in_place_is_seen(self):
        zone, zoned = self.zoned(ZoneEnvironment(intensity=0.5))
        where = at(0)
        self.pack(zoned, where=where)
        zone.settings.append(ZoneLights(enabled=False))
        zoned.boundLights = [PointLight()]
        zoned.setupZones(np.identity(4))
        assert self.pack(zoned, where=where)[1] == 0b1

    def test_a_light_given_to_a_zone_lights_only_inside(self):
        lamp = PointLight()
        setting = ZoneLights(lights=[])
        _zone, zoned = self.zoned(setting)
        zoned.boundLights = [lamp]
        zoned.setupZones(np.identity(4))
        outside = at(50)
        self.pack(zoned, path=('far',), where=outside)
        assert zoned.zoneState(('far',), outside, Box(1))[1] == 0
        setting.lights = [lamp]
        assert self.pack(zoned, path=('far',), where=outside)[1] == 0b1


class ImageProbe:
    """A probe that takes an upload into any layer it has."""

    arrayed, ready, lost, prefilter = True, True, 0, None

    def __init__(self):
        self.layers, self.uploads = 1, []

    def grow(self, layers):
        self.layers = layers

    def upload_light(self, light, layer):
        self.uploads.append(layer)
        return True


class TestImageLightsWhileZonesMove:
    def test_an_image_lit_zone_keeps_its_layer_while_another_zone_moves(self):
        from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight
        lit = Zone(size=(10, 10, 10), settings=[ZoneEnvironment(light=ImageBasedLight())])
        lift = Zone(size=(2, 2, 2), settings=[ZoneEnvironment(intensity=0.5)])
        zoned = ZonedPass([(lit, at(0)), (lift, at(30))])
        probe = zoned._ibl_probe = ImageProbe()
        zoned._zoneLighting = ('full', probe)
        placed = zoned.placeZones()[0]
        assert zoned.zoneProbeLayer(placed) == -1.0       # reserved, not yet filled
        zoned.uploadImageLights(probe)
        assert zoned.zoneProbeLayer(placed) == 1.0
        for height in (1.0, 2.0, 3.0):
            zoned.paths[Zone][1].matrix = at(30, height)
            placed = zoned.placeZones()[0]
            zoned.uploadImageLights(probe)
            assert zoned.zoneProbeLayer(placed) == 1.0
        assert probe.uploads == [1]


class TestAnObjectChangingInPlace:
    def test_an_object_scaled_where_it_stands_is_classified_again(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment()]), at(0))])
        zoned.placeZones()
        path = ('statue',)
        assert zoned.zoneState(path, at(0), Box(1))[0].kinds[0] == 0      # inside
        grown = at(0)
        grown[:3, :3] *= 20.0
        assert zoned.zoneState(path, grown, Box(1))[0].kinds[0] == 1      # across

    def test_an_object_whose_bounds_change_is_classified_again(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment()]), at(0))])
        zoned.placeZones()
        path, where = ('particles',), at(0)
        assert zoned.zoneState(path, where, Box(1))[0].kinds[0] == 0
        assert zoned.zoneState(path, where, Box(20))[0].kinds[0] == 1


class TestAGroupFrameByFrame:
    """Records made afresh each frame, the old ones let go, as the pass makes them."""

    @staticmethod
    def frame(positions):
        return [(None, None, at(x), Box(1), path, None) for path, x in positions]

    def test_a_member_moving_out_is_seen_though_its_matrix_is_new(self):
        """The moved member's new matrix is often made where the old one was."""
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment()]), at(0))])
        zoned.placeZones()
        zoned.setupZones(np.identity(4))
        shader = zoned.shader_program
        paths = [('tree', index) for index in range(3)]
        bounds = Box(1)

        def draw(matrices):
            members = [(None, None, matrix, bounds, path, None)
                       for path, matrix in zip(paths, matrices)]
            zoned.applyZonesToGroup(shader, members, key='trees')
        matrices = [at(x) for x in (-2.0, 0.0, 2.0)]
        draw(matrices)
        assert shader.zones[-1].kinds[0] == 0
        del matrices
        matrices = [at(x) for x in (30.0, 0.0, 2.0)]
        draw(matrices)
        assert shader.zones[-1].kinds[0] == 1

    def test_a_group_seen_in_part_keeps_one_entry(self):
        zoned = ZonedPass([(Zone(size=(10, 10, 10), settings=[ZoneEnvironment()]), at(0))])
        zoned.placeZones()
        zoned.setupZones(np.identity(4))
        shader = zoned.shader_program
        paths = [('tree', index) for index in range(6)]
        for first in range(4):
            visible = list(zip(paths, range(6)))[first:first + 2]
            zoned.applyZonesToGroup(shader, self.frame(visible), key='trees')
        assert len(zoned._zoneGroups) == 1
        assert len(zoned._zoneObjects) == 1


class TestOneZoneMoving:
    """Ten rooms along a street and a thousand still objects, one room creeping."""

    def street(self):
        pairs = [(Zone(size=(10, 10, 10), blend=1.0,
                       settings=[ZoneEnvironment(intensity=0.1 * (i + 1))]), at(100.0 * i))
                 for i in range(10)]
        zoned = ZonedPass(pairs)
        zoned.placeZones()
        zoned.setupZones(np.identity(4))
        records = [(None, None, at(x), Box(0.5), ('thing', index), None)
                   for index, x in enumerate(np.linspace(-20.0, 920.0, 1000))]
        zoned.refreshZones(records)
        counted = []
        real = zoned._classify
        zoned._classify = lambda items: counted.append(len(items)) or real(items)
        return zoned, records, counted

    def test_only_the_objects_near_it_are_classified_again(self):
        zoned, records, counted = self.street()
        for step in range(1, 4):
            zoned.paths[Zone][0].matrix = at(0.01 * step)
            zoned.placeZones()
            zoned.refreshZones(records)
        assert 0 < max(counted) < 150, counted

    def test_what_they_are_given_is_where_it_is_now(self):
        zoned, records, _counted = self.street()
        zoned.paths[Zone][3].matrix = at(0.0, 30.0)        # lifted clear of the street
        zoned.placeZones()
        zoned.refreshZones(records)
        for record in records:
            x = record[2][3, 0]
            reach = zoned._zoneObjects[id(record[4])].reach
            if abs(x - 300.0) < 4.0:
                assert reach is None, x
            elif abs(x - 400.0) < 4.0:
                assert reach.stack[0][0].zone is zoned.zones[4].zone


class CaptureProbe(ImageProbe):
    """A probe arrays of captures go into; ``takes`` says whether it takes one."""

    ENV_SIZE = 4

    def __init__(self, takes=True):
        super().__init__()
        self.takes, self.convolved = takes, []

    def convolve(self, cube, layer):
        self.convolved.append(layer)
        return self.takes


class CaptureTarget:
    """Where the faces go, and whether each stretch of them ended a whole cube."""

    size, cube = 4, 1

    def __init__(self):
        self.begun, self.ended = 0, []

    def begin(self):
        self.begun += 1

    def face(self, face):
        pass

    def end(self, whole):
        self.ended.append(whole)

    def release(self):
        self.released = True


class CapturingPass(ZonedPass):
    """A pass with one capturing room, drawing its captures into nothing."""

    def __init__(self, probe, draw=None):
        self.room = Zone(size=(10, 10, 10), settings=[ZoneEnvironment(capture=True)])
        super().__init__([(self.room, at(0))])
        self._ibl_probe = probe
        self._captureTarget = CaptureTarget()
        self.activeFrame = type('Frame', (), {'view': None, 'camera': None,
                                              'modelView': at(50)})()
        self.drawn = draw or (lambda records: None)
        self.shader_program = type('Program', (), {
            'use': lambda self, lit=True: None,
            'set_hdr_output': lambda self, on: None})()

    def frameGather(self):
        return None

    def applyViewFrame(self, frame, gl=True):
        pass

    def renderSet(self, matrix, gathered=None):
        return []

    def currentBackground(self):
        return None

    def setupViewLighting(self, view, lighting, fitted=True):
        pass

    def shaderRenderOpaque(self, records, id_map=None):
        self.drawn(records)

    def clearPlanarReflection(self):
        pass

    def frames(self, count):
        """Draw ``count`` frames' shares of the captures, asking for the room's layer."""
        lighting = ('full', self._ibl_probe)
        for _frame in range(count):
            self.renderZoneProbes([], lighting)
            self.zoneProbeLayer(self.placeZones()[0])


class TestCaptures:
    def test_a_cube_is_mip_mapped_only_when_its_last_face_is_drawn(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_ZONE_CAPTURE_FACES', '2')
        zoned = CapturingPass(CaptureProbe())
        zoned.frames(4)
        assert zoned._captureTarget.ended == [False, False, True]
        assert zoned._ibl_probe.convolved == [1]

    def test_a_failed_capture_is_not_drawn_again_and_the_others_are_kept(self, caplog):
        def broken(records):
            raise RuntimeError('no program')
        zoned = CapturingPass(CaptureProbe(), draw=broken)
        with caplog.at_level('ERROR', logger='OpenGLContext.passes.zonepass'):
            zoned.frames(5)
        assert zoned._captureTarget.begun == 1
        assert zoned._captureTarget.ended == [False]
        assert zoned._zoneCaptures is not None and zoned._zoneCaptures.given_up(zoned.room)
        failures = [r for r in caplog.records if 'capture failed' in r.getMessage()]
        assert len(failures) == 1 and failures[0].exc_info is not None
        assert zoned.zoneProbeLayer(zoned.zones[0]) == -1.0

    def test_a_probe_that_will_not_take_a_capture_stops_being_asked(self, caplog):
        from OpenGLContext.passes.zoneprobes import ATTEMPTS
        zoned = CapturingPass(CaptureProbe(takes=False))
        with caplog.at_level('WARNING', logger='OpenGLContext.passes.zonepass'):
            zoned.frames(ATTEMPTS + 5)
        assert zoned._ibl_probe.convolved == [1] * ATTEMPTS
        assert len([r for r in caplog.records if 'did not take' in r.getMessage()]) == 1

    def test_the_capture_target_goes_with_the_passs_gl_objects(self):
        zoned = CapturingPass(CaptureProbe())
        target = zoned._captureTarget
        zoned.disposeResources()
        assert target.released and zoned._captureTarget is None

    def test_a_zone_given_up_is_captured_again_once_the_probes_are_lost(self):
        def broken(records):
            raise RuntimeError('no program')
        zoned = CapturingPass(CaptureProbe(), draw=broken)
        zoned.frames(2)
        zoned.drawn = lambda records: None
        zoned._ibl_probe.lost += 1
        zoned.frames(3)
        assert zoned._ibl_probe.convolved


class TestPassState:
    def test_no_state_is_shared_between_passes_through_the_class(self):
        for name, value in vars(ZonesMixin).items():
            if not name.startswith('__'):
                assert not isinstance(value, (list, dict, set)), name

    def test_the_capture_faces_variable_is_read_once(self, monkeypatch):
        zoned = ZonedPass([])
        monkeypatch.setenv('OPENGLCONTEXT_ZONE_CAPTURE_FACES', '2')
        assert zoned.zoneCaptureFaces() == 2
        monkeypatch.setenv('OPENGLCONTEXT_ZONE_CAPTURE_FACES', '5')
        assert zoned.zoneCaptureFaces() == 2

    def test_the_definition_and_the_probes_agree_on_the_faces(self, monkeypatch):
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.passes.zoneprobes import FACES_PER_FRAME
        monkeypatch.delenv('OPENGLCONTEXT_ZONE_CAPTURE_FACES', raising=False)
        assert ContextDefinition().zoneCaptureFaces == FACES_PER_FRAME
        assert ZonedPass([]).zoneCaptureFaces() == FACES_PER_FRAME


def test_an_object_with_no_bounds_crosses_every_zone():
    class Unbounded:
        def getPoints(self):
            return ()
    low, high = ZonesMixin.worldBox(at(0), Unbounded())
    assert np.all(low < -1e6) and np.all(high > 1e6)
