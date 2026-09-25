"""Reading ``OGLC_zone`` and the shape table it names, in glTF 2.0 and 2.1.

The two documents here are the specification's own examples
(``docs/extensions/examples``), so the specification and the reader cannot
drift apart.
"""
import json
import logging
import os

import pytest

pytest.importorskip('pygltflib')

from OpenGLContext.loaders.gltf import fastdecode, loader, shapes, zoning
from OpenGLContext.scenegraph import audio as audionodes
from OpenGLContext.scenegraph.light import SpotLight
from OpenGLContext.scenegraph.zone import (
    AUDIO, ENVIRONMENT, LIGHTS, MIRRORS, REVERB, VISIBILITY, GRAVITY, Zone,
    ZoneEnvironment,
)
from OpenGLContext.scenegraph.zones import BOX, CAPSULE, SPHERE

EXAMPLES = os.path.join(os.path.dirname(__file__), '..', '..', 'docs',
                        'extensions', 'examples')


def example(version):
    with open(os.path.join(EXAMPLES, 'OGLC_zone-%s.gltf' % version)) as handle:
        return json.load(handle)


def load(body):
    return loader.load_gltf(json.dumps(body).encode('utf-8'),
                            base_url='http://example/zones.gltf')


def zone_node(**block):
    """A one-node document whose node is a zone of ``block``, over a 2.0 shape table."""
    return {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['OGLC_zone', 'KHR_implicit_shapes'],
        'extensions': {'KHR_implicit_shapes': {'shapes': [
            {'type': 'box', 'box': {'size': [2.0, 3.0, 4.0]}},
            {'type': 'sphere', 'sphere': {'radius': 5.0}},
            {'type': 'plane', 'plane': {'sizeX': 1.0, 'sizeZ': 1.0}},
        ]}},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'name': 'zone', 'extensions': {'OGLC_zone': block}}],
    }


class TestShapeTable:
    def test_a_2_0_document_reads_khr_implicit_shapes(self):
        g = fastdecode.decode_gltf(example('2.0'))
        table = shapes.document_shapes(g)
        assert [s.kind for s in table] == [BOX, BOX]
        assert table[0].size == (29.6, 10.2, 19.06)

    def test_a_2_1_document_reads_the_core_array(self):
        g = fastdecode.decode_gltf(example('2.1'))
        assert shapes.document_shapes(g) == shapes.document_shapes(
            fastdecode.decode_gltf(example('2.0')))

    def test_a_2_1_document_carrying_the_extension_too_uses_the_core_array(self):
        body = example('2.1')
        body['extensions']['KHR_implicit_shapes'] = {'shapes': [
            {'type': 'sphere', 'sphere': {'radius': 1.0}}]}
        table = shapes.document_shapes(fastdecode.decode_gltf(body))
        assert [s.kind for s in table] == [BOX, BOX]

    def test_the_core_array_is_not_read_in_a_2_0_document(self):
        body = example('2.1')
        body['asset']['version'] = '2.0'
        assert shapes.document_shapes(fastdecode.decode_gltf(body)) == []

    def test_dimensions_default_as_the_shapes_do(self):
        assert shapes.read_shape({'type': 'sphere'}).radius == 0.5
        capsule = shapes.read_shape({'type': 'capsule', 'capsule': {'height': 2.0}})
        assert (capsule.kind, capsule.height, capsule.radius_top) == (CAPSULE, 2.0, 0.25)

    def test_a_plane_is_not_a_zone_shape(self):
        assert shapes.read_shape({'type': 'plane', 'plane': {}}) is None

    @pytest.mark.parametrize('version,core', [('2.0', False), ('2.1', True),
                                              ('2.10', True), ('3.0', True),
                                              ('', False), ('two', False)])
    def test_which_versions_have_core_shapes(self, version, core):
        assert shapes.is_core_version(version) is core


class TestTheExamples:
    @pytest.fixture(params=['2.0', '2.1'])
    def scene(self, request):
        return load(example(request.param))

    def test_each_zone_node_becomes_a_zone(self, scene):
        assert [type(z) for z in scene.zones] == [Zone, Zone]

    def test_the_zone_sits_under_its_node(self, scene):
        naos = scene.getDEF('naos_interior')
        assert scene.zones[0] in naos.children

    def test_the_shape_and_rules_are_read(self, scene):
        naos = scene.zones[0]
        assert (naos.shapeType, tuple(naos.size)) == (BOX, (29.6, 10.2, 19.06))
        assert (naos.priority, naos.blend) == (0, 1.0)

    def test_the_environment(self, scene):
        environment = scene.zones[0].setting(ENVIRONMENT)
        assert isinstance(environment, ZoneEnvironment)
        assert environment.intensity == pytest.approx(0.12)
        assert not environment.capture

    def test_the_door_light_is_named(self, scene):
        lights = scene.zones[0].setting(LIGHTS)
        assert len(lights.lights) == 1 and isinstance(lights.lights[0], SpotLight)

    def test_an_unplaced_global_emitter_is_built_for_the_zone(self, scene):
        audio = scene.zones[1].setting(AUDIO)
        assert len(audio.emitters) == 1
        emitter = audio.emitters[0]
        assert isinstance(emitter, audionodes.AudioEmitter)
        assert scene.sounds['west-chamber-tone'] is emitter

    def test_the_reverb(self, scene):
        reverb = scene.zones[1].setting(REVERB)
        assert (reverb.level, reverb.decay, reverb.damping) == pytest.approx(
            (0.35, 2.2, 0.5))

    def test_the_two_versions_read_the_same(self):
        def summary(scene):
            return [(z.shapeType, tuple(z.size), z.priority, z.blend, z.keys())
                    for z in scene.zones]
        assert summary(load(example('2.0'))) == summary(load(example('2.1')))


class TestReading:
    def test_a_zone_with_no_extensions(self):
        scene = load(zone_node(shape=0))
        assert scene.zones[0].settings == []

    def test_a_missing_shape_is_no_zone(self, caplog):
        with caplog.at_level(logging.WARNING):
            scene = load(zone_node(blend=1.0))
        assert scene.zones == []
        assert 'shape' in caplog.text

    def test_an_out_of_range_shape_is_no_zone(self):
        assert load(zone_node(shape=7)).zones == []

    def test_a_plane_is_no_zone(self):
        assert load(zone_node(shape=2)).zones == []

    def test_a_sphere(self):
        zone = load(zone_node(shape=1)).zones[0]
        assert (zone.shapeType, zone.radius) == (SPHERE, 5.0)

    def test_an_unknown_extension_is_reported_once_and_the_rest_apply(self, caplog):
        with caplog.at_level(logging.WARNING):
            scene = load(zone_node(shape=0, environment={'intensity': 0.5},
                                   extensions={'EXT_unheard_of': {'x': 1}}))
        assert scene.zones[0].keys() == [ENVIRONMENT]
        assert caplog.text.count('EXT_unheard_of') == 1

    def test_false_switches_an_extension_off(self):
        scene = load(zone_node(shape=0, extensions={
            'KHR_lights_punctual': False, 'KHR_audio_emitter': False,
            'OGLC_hook': {'mirror': False}}))
        zone = scene.zones[0]
        for key in (LIGHTS, AUDIO, MIRRORS):
            assert not zone.setting(key).enabled

    def test_a_captured_environment(self):
        zone = load(zone_node(shape=0, environment={
            'capture': {'position': [0.0, -1.0, 0.0]}})).zones[0]
        environment = zone.setting(ENVIRONMENT)
        assert environment.capture
        assert tuple(environment.captureCentre) == (0.0, -1.0, 0.0)

    def test_gravity(self):
        zone = load(zone_node(shape=0, extensions={'OMI_physics_gravity': {
            'type': 'directional', 'gravity': 3.0, 'direction': [0, 1, 0],
            'replace': True}})).zones[0]
        gravity = zone.setting(GRAVITY)
        assert (gravity.gravity, tuple(gravity.direction), gravity.replace) == (
            3.0, (0.0, 1.0, 0.0), True)

    def test_visibility_names_nodes(self):
        body = zone_node(shape=0, extensions={'KHR_node_visibility': {
            'nodes': [1], 'visible': False}})
        body['nodes'].append({'name': 'secret'})
        body['scenes'][0]['nodes'].append(1)
        scene = load(body)
        visibility = scene.zones[0].setting(VISIBILITY)
        assert visibility.nodes == [scene.getDEF('secret')]
        assert not visibility.visible

    def test_visibility_names_what_a_hook_put_in_the_nodes_place(self):
        """A node hook that takes the node's slot leaves the loader's own
        Transform out of the scene; the zone controls what is drawn."""
        from OpenGLContext.loaders.gltf import hooks
        from OpenGLContext.scenegraph.group import Group
        body = zone_node(shape=0, extensions={'KHR_node_visibility': {
            'nodes': [1], 'visible': False}})
        body['nodes'].append({'name': 'secret',
                              'extras': {'OGLC_hook': 'test:stand-in'}})
        body['scenes'][0]['nodes'].append(1)
        hooks.register('test:stand-in', lambda ctx: (Group(), True))
        try:
            scene = load(body)
        finally:
            hooks.unregister('test:stand-in')
        visibility = scene.zones[0].setting(VISIBILITY)
        assert visibility.nodes == [scene.getDEF('secret')]
        assert isinstance(visibility.nodes[0], Group)

    def test_a_named_light_node_without_a_light_is_reported(self, caplog):
        body = zone_node(shape=0, extensions={'KHR_lights_punctual': {'nodes': [0]}})
        body['extensions']['KHR_lights_punctual'] = {'lights': [{'type': 'point'}]}
        with caplog.at_level(logging.WARNING):
            zone = load(body).zones[0]
        assert zone.setting(LIGHTS).lights == []
        assert 'carries no light' in caplog.text


class TestRegistry:
    def test_the_engine_reads_its_own_extensions(self):
        assert set(zoning.BUILTIN) == {
            'KHR_lights_punctual', 'KHR_audio_emitter', 'KHR_node_visibility',
            'OGLC_hook', 'OMI_physics_gravity', 'EXT_lights_image_based'}

    def test_an_application_can_add_a_reader(self):
        from OpenGLContext.scenegraph.zone import ZoneReverb

        def read(block, reading):
            return ZoneReverb(level=float(block['wet']))
        zoning.register_scoped('GAME_echo', read)
        try:
            zone = load(zone_node(shape=0, extensions={'GAME_echo': {'wet': 0.9}})).zones[0]
        finally:
            zoning.unregister_scoped('GAME_echo')
        assert zone.setting(REVERB).level == pytest.approx(0.9)
        assert 'GAME_echo' not in zoning.registered_scoped()


class TestMalformedValues:
    """One bad value in a zone costs the value, or the zone, never the load."""

    @pytest.mark.parametrize('block, check', [
        ({'priority': 'high'}, lambda zone: zone.priority == 0),
        ({'priority': 2.5}, lambda zone: zone.priority == 0),
        ({'blend': 'x'}, lambda zone: zone.blend == 0.0),
        ({'blend': float('inf')}, lambda zone: zone.blend == 0.0),
        ({'environment': {'intensity': 'dim'}},
         lambda zone: zone.setting(ENVIRONMENT).intensity == 1.0),
        ({'environment': {'capture': {'position': [1.0]}}},
         lambda zone: tuple(zone.setting(ENVIRONMENT).captureCentre) == (0.0, 0.0, 0.0)),
        ({'reverb': {'level': 'x', 'decay': -3.0}},
         lambda zone: (zone.setting(REVERB).level, zone.setting(REVERB).decay)
         == (pytest.approx(0.4), 0.0)),
    ])
    def test_a_malformed_value_is_its_default(self, block, check, caplog):
        with caplog.at_level(logging.WARNING):
            scene = load(zone_node(shape=0, **block))
        zone, = scene.zones
        assert check(zone)
        assert caplog.text

    def test_a_box_without_three_sizes_is_no_zone(self, caplog):
        body = zone_node(shape=0)
        body['extensions']['KHR_implicit_shapes']['shapes'][0]['box']['size'] = [2.0, 3.0]
        with caplog.at_level(logging.WARNING):
            scene = load(body)
        assert scene.zones == []
        assert 'shape' in caplog.text

    def test_a_box_with_a_size_that_is_no_number_is_no_zone(self):
        body = zone_node(shape=0)
        body['extensions']['KHR_implicit_shapes']['shapes'][0]['box']['size'] = [
            2.0, float('nan'), 1.0]
        assert load(body).zones == []
