"""KHR_gaussian_splatting primitives read as GaussianSplats nodes, and written back.

Each document is assembled here as glTF JSON with its buffer in a data URI,
so the accessors can be given each component type the extension allows.
"""
import base64
import json

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
from OpenGLContext.scenegraph.gaussiansplats import GaussianSplats, HARMONIC_FIELDS, from_arrays

FLOAT, BYTE, UNSIGNED_BYTE, UNSIGNED_SHORT = 5126, 5120, 5121, 5123
KINDS = {1: 'SCALAR', 3: 'VEC3', 4: 'VEC4'}
PREFIX = 'KHR_gaussian_splatting:'

POSITIONS = np.array([(0, 0, 0), (1, 2, 3)], np.float32)
ROTATIONS = np.array([(0, 0, 0, 1), (0, 0.7071068, 0, 0.7071068)], np.float32)
SCALES = np.array([(0.1, 0.2, 0.3), (0.5, 0.5, 0.5)], np.float32)
OPACITIES = np.array([0.25, 1.0], np.float32)
DC = np.array([(1, 0, 0), (0, 1, 0)], np.float32)


def _document(attributes, extension=None, mode=0, node=None, material=False):
    """glTF JSON bytes of one node with one primitive

    `attributes` maps a semantic to an array, or to (array, component type,
    normalized) for an integer accessor.
    """
    blob = bytearray()
    accessors, views, named = [], [], {}
    for semantic, value in attributes.items():
        array, component, normalized = (value if isinstance(value, tuple)
                                        else (value, FLOAT, False))
        array = np.ascontiguousarray(array)
        blob.extend(b'\0' * (-len(blob) % 4))
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': array.nbytes})
        blob.extend(array.tobytes())
        accessor = {'bufferView': len(views) - 1, 'componentType': component,
                    'count': len(array), 'type': KINDS[1 if array.ndim == 1 else array.shape[1]]}
        if normalized:
            accessor['normalized'] = True
        if semantic == 'POSITION':
            accessor['min'] = array.min(0).tolist()
            accessor['max'] = array.max(0).tolist()
        accessors.append(accessor)
        named[semantic] = len(accessors) - 1
    primitive = {'attributes': named, 'mode': mode, 'extensions': {
        'KHR_gaussian_splatting': extension if extension is not None else
        {'kernel': 'ellipse', 'colorSpace': 'srgb_rec709_display'}}}
    document = {
        'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
        'nodes': [dict(node or {}, mesh=0)], 'meshes': [{'primitives': [primitive]}],
        'accessors': accessors, 'bufferViews': views,
        'buffers': [{'byteLength': len(blob), 'uri': 'data:application/octet-stream;base64,'
                     + base64.b64encode(bytes(blob)).decode('ascii')}],
        'extensionsUsed': ['KHR_gaussian_splatting']}
    if material:
        document['materials'] = [{'pbrMetallicRoughness': {'baseColorFactor': [0, 0, 1, 1]}}]
        primitive['material'] = 0
    return json.dumps(document).encode('utf-8')


def _attributes(**replaced):
    found = {'POSITION': POSITIONS, PREFIX + 'ROTATION': ROTATIONS,
             PREFIX + 'SCALE': SCALES, PREFIX + 'OPACITY': OPACITIES,
             PREFIX + 'SH_DEGREE_0_COEF_0': DC}
    for name, value in replaced.items():
        key = name if name == 'POSITION' else PREFIX + name
        if value is None:
            found.pop(key)
        else:
            found[key] = value
    return found


def _found(scene, kind):
    """Every node of `kind` under the scene's group, depth first"""
    found, pending = [], [scene.group]
    while pending:
        node = pending.pop()
        if isinstance(node, kind):
            found.append(node)
        pending.extend(getattr(node, 'children', None) or [])
    return found


def _splats(data):
    found = _found(gltf.load_gltf(data), GaussianSplats)
    assert len(found) == 1
    return found[0]


def test_a_splat_primitive_is_read_as_a_gaussian_splats_node():
    node = _splats(_document(_attributes()))
    assert np.allclose(node.positions, POSITIONS)
    assert np.allclose(node.orientations, ROTATIONS)
    assert np.allclose(node.scales, SCALES)
    assert np.allclose(node.opacities, OPACITIES)
    assert np.allclose(node.sphericalHarmonicsDegree0Coef0, DC)
    assert node.colorSpace == 'SRGB_REC709_DISPLAY'
    assert node.splats().count == 2 and node.splats().degree == 0


def test_the_linear_colour_space_is_the_nodes():
    extension = {'kernel': 'ellipse', 'colorSpace': 'lin_rec709_display'}
    assert _splats(_document(_attributes(), extension)).colorSpace == 'LIN_REC709_DISPLAY'


def test_integer_attributes_are_read_as_the_extension_allows():
    rotations = np.round(ROTATIONS * 127).astype(np.int8)
    opacities = np.round(OPACITIES * 65535).astype(np.uint16)
    node = _splats(_document(_attributes(
        ROTATION=(rotations, BYTE, True),
        SCALE=(np.array([(1, 2, 3), (4, 5, 6)], np.uint8), UNSIGNED_BYTE, False),
        OPACITY=(opacities, UNSIGNED_SHORT, True))))
    assert np.allclose(node.orientations, ROTATIONS, atol=0.01)
    assert np.allclose(node.scales, [(1, 2, 3), (4, 5, 6)])
    assert np.allclose(node.opacities, OPACITIES, atol=1e-4)


def test_each_degree_present_is_read():
    rng = np.random.default_rng(3)
    first = {'SH_DEGREE_1_COEF_%d' % index: rng.normal(size=(2, 3)).astype(np.float32)
             for index in range(3)}
    node = _splats(_document(_attributes(**first)))
    assert node.splats().degree == 1
    for index in range(3):
        assert np.allclose(getattr(node, 'sphericalHarmonicsDegree1Coef%d' % index),
                           first['SH_DEGREE_1_COEF_%d' % index])


def test_the_nodes_transform_places_the_splats():
    data = _document(_attributes(), node={'translation': [5, 0, 0]})
    scene = gltf.load_gltf(data)
    (node,) = _found(scene, GaussianSplats)
    parents = [group for group in _found(scene, object)
               if node in (getattr(group, 'children', None) or [])]
    assert np.allclose(parents[0].translation, (5, 0, 0))


def test_the_material_is_not_used_for_the_splats():
    scene = gltf.load_gltf(_document(_attributes(), material=True))
    assert len(_found(scene, GaussianSplats)) == 1
    assert not [node for node in _found(scene, object) if getattr(node, 'geometry', None)]


def test_a_primitive_missing_a_required_attribute_is_read_as_points(caplog):
    with caplog.at_level('WARNING'):
        scene = gltf.load_gltf(_document(_attributes(OPACITY=None)))
    assert not _found(scene, GaussianSplats)
    shapes = [node for node in _found(scene, object) if getattr(node, 'geometry', None)]
    assert len(shapes) == 1 and shapes[0].geometry.draw_mode == 0
    assert any('OPACITY' in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize('extension, word', [
    ({'kernel': 'customShape', 'colorSpace': 'srgb_rec709_display'}, 'kernel'),
    ({'kernel': 'ellipse', 'colorSpace': 'acescg'}, 'colorSpace'),
    ({'kernel': 'ellipse', 'colorSpace': 'srgb_rec709_display',
      'sortingMethod': 'viewDepth'}, 'sortingMethod'),
    ({'kernel': 'ellipse', 'colorSpace': 'srgb_rec709_display',
      'projection': 'orthographic'}, 'projection'),
])
def test_values_the_extension_does_not_define_are_reported(extension, word, caplog):
    with caplog.at_level('WARNING'):
        node = _splats(_document(_attributes(), extension))
    assert node.colorSpace == 'SRGB_REC709_DISPLAY'
    assert any(word in record.getMessage() for record in caplog.records)


def test_a_primitive_not_drawn_as_points_is_reported(caplog):
    with caplog.at_level('WARNING'):
        node = _splats(_document(_attributes(), mode=4))
    assert node.splats().count == 2
    assert any('mode' in record.getMessage() for record in caplog.records)


def test_a_node_written_reads_back_the_same():
    rng = np.random.default_rng(8)
    harmonics = [rng.normal(size=(2, 3)) for _ in range(9)]
    node = from_arrays(POSITIONS, ROTATIONS, SCALES, OPACITIES, harmonics,
                       color_space='LIN_REC709_DISPLAY')
    data = write_glb(SceneNode(mesh=node, translation=(0, 1, 0)))
    found = _splats(data)
    assert found.colorSpace == 'LIN_REC709_DISPLAY'
    assert found.splats().degree == 2
    for name in ('positions', 'orientations', 'scales', 'opacities'):
        assert np.allclose(getattr(found, name), getattr(node, name))
    for name, values in zip(HARMONIC_FIELDS, harmonics):
        assert np.allclose(getattr(found, name), values)
    assert not len(found.sphericalHarmonicsDegree3Coef0)
    assert json.loads(data[20:20 + int.from_bytes(data[12:16], 'little')])[
        'extensionsUsed'] == ['KHR_gaussian_splatting']


def test_a_node_with_defaults_is_written_whole():
    node = GaussianSplats(positions=[(0, 0, 0)], scales=[(1, 1, 1)],
                          sphericalHarmonicsDegree0Coef0=[(0, 0, 0)])
    found = _splats(write_glb(SceneNode(mesh=node)))
    assert np.allclose(found.orientations, [(0, 0, 0, 1)])
    assert np.allclose(found.opacities, [1.0])


@pytest.mark.parametrize('fields, word', [
    ({}, 'at least one'),
    ({'positions': [(0, 0, 0)], 'sphericalHarmonicsDegree0Coef0': [(0, 0, 0)]}, 'scale'),
    ({'positions': [(0, 0, 0)], 'scales': [(1, 1, 1)]}, 'sphericalHarmonicsDegree0Coef0'),
])
def test_a_node_short_of_values_is_refused(fields, word):
    with pytest.raises(ValueError, match=word):
        write_glb(SceneNode(mesh=GaussianSplats(**fields)))
