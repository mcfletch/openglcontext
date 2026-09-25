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
    """A bounding volume of eight corners about the origin."""

    def __init__(self, half):
        self.half = half

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


class TestAudio:
    def test_zone_emitters_are_heard_inside_and_the_reverb_is_the_zones(self):
        from OpenGLContext.audio.areas import apply_zones
        birds, music = AudioEmitter(type='global'), AudioEmitter(type='global')
        zones = placed_zones([(Zone(size=(10, 10, 10), blend=2.0, settings=[
            ZoneAudio(emitters=[birds]), ZoneReverb(level=0.5, decay=2.0)]), at(0))])

        class Engine:
            class reverb:
                level = decay = damping = None
        engine = Engine()
        apply_zones(engine, [birds, music], zones, (0, 0, 0))
        assert birds.zoneGain == 1.0 and music.zoneGain == 1.0
        assert engine.reverb.level == pytest.approx(0.5)
        apply_zones(engine, [birds, music], zones, (6, 0, 0))
        assert 0.0 < birds.zoneGain < 1.0
        apply_zones(engine, [birds, music], zones, (50, 0, 0))
        assert birds.zoneGain == 0.0 and music.zoneGain == 1.0
        assert engine.reverb.level == 0.0

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
        path, where = ('ground',), at(0)

        def reached():
            zoned.zoneState(path, where, Everything())
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
            one = zoned._classifyObject(record[2], record[3]).reach
            assert (None if one is None else [(id(z), i) for z, i in one.stack]) == \
                (None if found is None else [(id(z), i) for z, i in found.stack])


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
        zoned.applyZonesToGroup(shader, members)
        zoned.applyZonesToGroup(shader, members)
        assert calls == [1]
        assert shader.zones[-1].light[0][0] == pytest.approx(0.2)
        moved = list(members)
        moved[0] = (None, None, at(30.0), Box(1), ('tree', -2.0), None)
        zoned.applyZonesToGroup(shader, moved)
        assert calls == [1, 1]
        assert shader.zones[-1].kinds[0] == 1        # the group now crosses the edge


def test_an_object_with_no_bounds_crosses_every_zone():
    class Unbounded:
        def getPoints(self):
            return ()
    low, high = ZonesMixin.worldBox(at(0), Unbounded())
    assert np.all(low < -1e6) and np.all(high > 1e6)
