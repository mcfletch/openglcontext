"""The fast glTF JSON decoder builds the same document pygltflib would.

pygltflib decodes JSON through dataclasses_json, which resolves type hints and
runs subclass checks per object; on a rigged character (thousands of accessors
and animation channels) that runs into seconds. :mod:`fastdecode` builds the
same pygltflib objects directly. These tests hold it to one standard: the object
graph it produces is indistinguishable from pygltflib's own, over documents that
exercise every shape the format offers -- nested structs, lists of structs,
custom vertex attributes, morph targets, animations, skins and extensions.
"""
import dataclasses
import json
import struct

import pygltflib
import pytest

from OpenGLContext.loaders.gltf.fastdecode import decode_gltf, load_glb


def _same(a, b, path='root'):
    """Assert two decoded glTF object graphs are structurally identical."""
    if dataclasses.is_dataclass(a) and not isinstance(a, type):
        assert type(a) is type(b), '%s: %s != %s' % (path, type(a), type(b))
        for f in dataclasses.fields(a):
            _same(getattr(a, f.name), getattr(b, f.name), '%s.%s' % (path, f.name))
    elif isinstance(a, pygltflib.Attributes):
        assert isinstance(b, pygltflib.Attributes), '%s: Attributes' % path
        _same(a.__dict__, b.__dict__, path)
    elif isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), '%s: %r != %r' % (path, a, b)
        for k in a:
            _same(a[k], b[k], '%s[%r]' % (path, k))
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), '%s: len %d != %d' % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _same(x, y, '%s[%d]' % (path, i))
    else:
        assert a == b, '%s: %r != %r' % (path, a, b)


#: A document that puts one of every reachable shape in front of the decoder:
#: a scene and node hierarchy, a skinned + morphed mesh with a custom vertex
#: attribute, an animation, a material with an extension, and document extras.
_DOC = {
    'asset': {'version': '2.0', 'generator': 'test'},
    'scene': 0,
    'scenes': [{'name': 'main', 'nodes': [0]}],
    'nodes': [
        {'name': 'root', 'children': [1], 'translation': [0.0, 1.0, 0.0]},
        {'name': 'mesh_node', 'mesh': 0, 'skin': 0,
         'rotation': [0.0, 0.0, 0.0, 1.0]},
        {'name': 'joint', 'matrix': [1, 0, 0, 0, 0, 1, 0, 0,
                                     0, 0, 1, 0, 0, 0, 0, 1]},
    ],
    'meshes': [{'name': 'm', 'primitives': [{
        'attributes': {'POSITION': 0, 'NORMAL': 1, 'JOINTS_0': 2,
                       'WEIGHTS_0': 3, 'TEXCOORD_2': 4},
        'indices': 5, 'material': 0, 'mode': 4,
        'targets': [{'POSITION': 6}],
    }], 'weights': [0.0]}],
    'skins': [{'joints': [2], 'inverseBindMatrices': 7, 'skeleton': 2}],
    'animations': [{'name': 'wave',
                    'channels': [{'sampler': 0,
                                  'target': {'node': 2, 'path': 'rotation'}}],
                    'samplers': [{'input': 8, 'output': 9,
                                  'interpolation': 'LINEAR'}]}],
    'materials': [{'name': 'red', 'alphaMode': 'BLEND',
                   'pbrMetallicRoughness': {'baseColorFactor': [1, 0, 0, 1]},
                   'extensions': {'KHR_materials_emissive_strength':
                                  {'emissiveStrength': 2.0}}}],
    'accessors': [
        {'bufferView': i, 'componentType': 5126, 'count': 3, 'type': 'VEC3'}
        for i in range(10)
    ],
    'bufferViews': [{'buffer': 0, 'byteOffset': i * 12, 'byteLength': 12}
                    for i in range(10)],
    'buffers': [{'byteLength': 120}],
    'extensionsUsed': ['KHR_materials_emissive_strength'],
    'extensions': {'KHR_lights_punctual': {'lights': [{'type': 'point'}]}},
    'extras': {'author': 'test'},
}


def test_matches_pygltflib_over_full_document():
    text = json.dumps(_DOC)
    _same(decode_gltf(text), pygltflib.GLTF2.from_json(text, infer_missing=True))


def test_custom_vertex_attribute_survives():
    attrs = decode_gltf(json.dumps(_DOC)).meshes[0].primitives[0].attributes
    assert attrs.TEXCOORD_2 == 4          # a glTF name pygltflib does not declare
    assert attrs.POSITION == 0


def test_absent_fields_take_the_documented_default():
    # A material naming only its name still reports alphaMode OPAQUE, the way
    # pygltflib's own decode does -- the value the loader reads downstream.
    g = decode_gltf('{"materials":[{"name":"m"}]}')
    assert g.materials[0].alphaMode == 'OPAQUE'
    assert g.materials[0].emissiveFactor == [0.0, 0.0, 0.0]


def _glb_bytes(doc, binary):
    """Pack a document and a binary blob into GLB container bytes."""
    js = json.dumps(doc).encode('utf-8')
    js += b' ' * (-len(js) % 4)
    bina = bytes(binary)
    bina += b'\x00' * (-len(bina) % 4)
    total = 12 + 8 + len(js) + 8 + len(bina)
    out = struct.pack('<III', 0x46546C67, 2, total)
    out += struct.pack('<II', len(js), 0x4E4F534A) + js
    out += struct.pack('<II', len(bina), 0x004E4942) + bina
    return out


def test_glb_decode_sets_binary_blob():
    blob = bytes(range(120))
    data = _glb_bytes(_DOC, blob)
    g = load_glb(data)
    assert g.binary_blob() == blob
    _same(g.meshes[0], pygltflib.GLTF2.load_from_bytes(data).meshes[0])


def test_bad_json_is_a_value_error():
    with pytest.raises(ValueError):
        decode_gltf('{not json')


def test_non_object_document_is_a_value_error():
    with pytest.raises(ValueError):
        decode_gltf('[1, 2, 3]')


@pytest.mark.parametrize('data,message', [
    (b'gl', 'shorter than'),
    (b'NOPE' + b'\x00' * 8, 'bad magic'),
    (struct.pack('<III', 0x46546C67, 2, 12), 'no JSON chunk'),
])
def test_malformed_glb_is_a_value_error(data, message):
    with pytest.raises(ValueError, match=message):
        load_glb(data)
