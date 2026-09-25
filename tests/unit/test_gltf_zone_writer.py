"""Zones written by the engine's glTF writer are the zones its loader reads.

``GLTFWriter.add_zone`` writes an ``OGLC_zone`` node over a
``KHR_implicit_shapes`` shape, and the looping ``KHR_audio_emitter`` sounds it
plays; every test writes a document and reads it back through the loader, so
the format has one writer and one reader and they agree.
"""
import json

import pytest
import numpy as np

pytest.importorskip('pygltflib')

from OpenGLContext.loaders.gltf import loader
from OpenGLContext.loaders.gltf.writer import (
    GLTFWriter, GlobalSound, ZoneNode, zone_box,
)
from OpenGLContext.scenegraph.zone import AUDIO, ENVIRONMENT, REVERB
from OpenGLContext.scenegraph.zones import BOX
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

BIRDS = GlobalSound('birdsong', 'audio/birdsong.wav', gain=0.45)
SURF = GlobalSound('surf', 'audio/surf.wav', gain=0.55)


def _written(*zones):
    writer = GLTFWriter()
    for zone in zones:
        writer.add_zone(zone)
    return writer


def _loaded(writer):
    return loader.load_gltf(writer.to_gltf(), base_url='http://example/zones.gltf')


def _forest(**named):
    named.setdefault('sounds', (BIRDS,))
    return ZoneNode('forest-1', zone_box((40.0, 12.0, 80.0)),
                    translation=(10.0, 2.0, -5.0), rotation=(0.0, 0.0, 0.0, 1.0),
                    priority=2, blend=3.0, **named)


class TestAZoneReadsBackAsWritten:
    def test_its_shape_and_rules(self):
        zone, = _loaded(_written(_forest())).zones
        assert zone.shapeType == BOX
        assert tuple(zone.size) == pytest.approx((40.0, 12.0, 80.0))
        assert zone.priority == 2
        assert zone.blend == pytest.approx(3.0)

    def test_it_is_placed_where_it_was_written(self):
        scene = _loaded(_written(_forest()))
        node = scene.node_transforms[0]
        assert scene.zones[0] in node.children
        assert tuple(node.translation) == pytest.approx((10.0, 2.0, -5.0))

    def test_its_environment_and_reverb(self):
        zone, = _loaded(_written(_forest(
            environment={'capture': {'position': [1.0, 2.0, 3.0]}},
            reverb={'level': 0.45, 'decay': 1.9, 'damping': 0.5}))).zones
        assert zone.setting(ENVIRONMENT) is not None
        assert zone.setting(REVERB).decay == pytest.approx(1.9)

    def test_the_sound_it_plays(self):
        scene = _loaded(_written(_forest()))
        zone, = scene.zones
        emitters = zone.setting(AUDIO).emitters
        assert len(emitters) == 1
        assert scene.sounds['birdsong'] is emitters[0]


class TestSoundsSharedBetweenZones:
    def test_a_sound_two_zones_play_is_written_once(self):
        writer = _written(_forest(), ZoneNode('forest-2', zone_box((1, 1, 1)),
                                               sounds=(BIRDS,)),
                          ZoneNode('causeway-1', zone_box((1, 1, 1)),
                                   sounds=(SURF,)))
        emitter = writer.document()['extensions']['KHR_audio_emitter']
        assert [one['uri'] for one in emitter['audio']] == [
            'audio/birdsong.wav', 'audio/surf.wav']
        assert [one['gain'] for one in emitter['emitters']] == [0.45, 0.55]
        assert all(one['type'] == 'global' for one in emitter['emitters'])

    def test_the_extensions_are_declared(self):
        used = _written(_forest()).document()['extensionsUsed']
        assert {'OGLC_zone', 'KHR_implicit_shapes', 'KHR_audio_emitter'} <= set(used)

    def test_a_zone_that_plays_nothing_declares_no_audio(self):
        document = _written(_forest(sounds=())).document()
        assert 'KHR_audio_emitter' not in document['extensionsUsed']
        assert 'KHR_audio_emitter' not in document['extensions']


class TestTheDocumentAsText:
    def test_a_document_with_no_binary_chunk_is_json(self):
        document = json.loads(_written(_forest()).to_gltf())
        assert document['asset']['version'] == '2.0'

    def test_a_document_with_mesh_data_needs_a_glb(self):
        writer = _written(_forest())
        writer.add_mesh(PBRMesh(positions=np.zeros((3, 3), 'f'),
                                indices=np.array([0, 1, 2], 'u4')))
        with pytest.raises(ValueError):
            writer.to_gltf()
