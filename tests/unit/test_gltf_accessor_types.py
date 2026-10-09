"""glTF accessor component types beyond the core set, and quantized attributes.

``KHR_accessor_float16`` (componentType 5131) and ``KHR_accessor_float64``
(5130) are readable wherever a float accessor is, and ``KHR_mesh_quantization``
normalized integers are dequantized for every attribute that allows them:
positions, normals, tangents and morph-target deltas. Every document here is
built in the test; no GL, no network.
"""
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.gltf import load_gltf
from OpenGLContext.loaders.gltf import accessors as ga
from OpenGLContext.loaders.gltf.fastdecode import decode_gltf
from OpenGLContext.loaders.gltf.writer import _pack_glb
from OpenGLContext.loaders.resolver import Resolver

HALF, DOUBLE, BYTE, SHORT, UBYTE, FLOAT = 5131, 5130, 5120, 5122, 5121, 5126


class _Blob:
    """A binary buffer assembled view by view, each view four-byte aligned."""

    def __init__(self):
        self.data = bytearray()
        self.views = []

    def view(self, array, align=8):
        self.data.extend(b'\0' * (-len(self.data) % align))
        raw = np.ascontiguousarray(array).tobytes()
        self.views.append({'buffer': 0, 'byteOffset': len(self.data),
                           'byteLength': len(raw)})
        self.data.extend(raw)
        return len(self.views) - 1


def _triangle_document(blob, attributes, accessors, used=(), targets=None,
                       animations=None):
    """One node, one mesh, one triangle primitive over ``attributes``."""
    primitive = {'attributes': attributes}
    if targets:
        primitive['targets'] = targets
    doc = {
        'asset': {'version': '2.0'},
        'scene': 0, 'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [primitive]}],
        'accessors': accessors,
        'bufferViews': blob.views,
        'buffers': [{'byteLength': len(blob.data)}],
    }
    if targets:
        doc['meshes'][0]['weights'] = [0.0] * len(targets)
    if used:
        doc['extensionsUsed'] = list(used)
        doc['extensionsRequired'] = list(used)
    if animations:
        doc['animations'] = animations
    return doc


def _glb(doc, blob):
    return _pack_glb(doc, bytes(blob.data))


def _mesh(scene):
    """The one PBRMesh a single-triangle document builds."""
    stack = [scene.group]
    while stack:
        node = stack.pop()
        geometry = getattr(node, 'geometry', None)
        if geometry is not None:
            return geometry
        stack.extend(getattr(node, 'children', None) or [])
    raise AssertionError('no Shape in the loaded scene')


TRIANGLE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float64)


def _accessor(view, component, kind, count, normalized=False, **extra):
    acc = {'bufferView': view, 'componentType': component, 'type': kind,
           'count': count}
    if normalized:
        acc['normalized'] = True
    acc.update(extra)
    return acc


class TestComponentDtypes:
    def test_half_and_double_are_known_component_types(self):
        assert ga._component_dtype(HALF) == np.float16
        assert ga._component_dtype(DOUBLE) == np.float64

    def test_float_components_cover_all_three_widths(self):
        assert ga.FLOAT_COMPONENTS == frozenset((HALF, FLOAT, DOUBLE))


class TestFloat16:
    def test_positions_read_from_half_floats(self):
        blob = _Blob()
        positions = (TRIANGLE * 2.5).astype(np.float16)
        view = blob.view(positions)
        doc = _triangle_document(
            blob, {'POSITION': 0},
            [_accessor(view, HALF, 'VEC3', 3, min=[0, 0, 0], max=[2.5, 2.5, 0])],
            used=['KHR_accessor_float16'])
        mesh = _mesh(load_gltf(_glb(doc, blob)))
        got = np.asarray(mesh.positions, np.float32).reshape(-1, 3)
        assert np.array_equal(got, positions.astype(np.float32))

    def test_half_float_normals_and_texcoords(self):
        blob = _Blob()
        pv = blob.view(TRIANGLE.astype(np.float32))
        nv = blob.view(np.tile([0, 0, 1], (3, 1)).astype(np.float16))
        uv = blob.view(np.array([[0, 0], [0.5, 0], [0, 0.25]], np.float16))
        doc = _triangle_document(
            blob, {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2},
            [_accessor(pv, FLOAT, 'VEC3', 3), _accessor(nv, HALF, 'VEC3', 3),
             _accessor(uv, HALF, 'VEC2', 3)],
            used=['KHR_accessor_float16'])
        mesh = _mesh(load_gltf(_glb(doc, blob)))
        assert np.allclose(np.asarray(mesh.normals).reshape(-1, 3), [0, 0, 1])
        assert np.allclose(np.asarray(mesh.texcoords).reshape(-1, 2)[1], [0.5, 0])

    def test_half_float_is_not_dequantized_as_an_integer(self):
        # A float component type is never "normalized", whatever the flag says.
        data = np.array([[0.5, 2.0]], np.float16)
        doc = {'accessors': [_accessor(0, HALF, 'VEC2', 1, normalized=True)],
               'bufferViews': [{'buffer': 0, 'byteLength': data.nbytes}],
               'buffers': [{'byteLength': data.nbytes}], 'asset': {'version': '2.0'}}
        g = decode_gltf(doc)
        resolver = Resolver()
        resolver._buffers = {0: data.tobytes()}
        assert ga._read_normalized(g, 0, resolver).tolist() == [[0.5, 2.0]]


class TestFloat64:
    def test_positions_read_from_doubles(self):
        blob = _Blob()
        positions = TRIANGLE * 3.0
        view = blob.view(positions)
        doc = _triangle_document(
            blob, {'POSITION': 0}, [_accessor(view, DOUBLE, 'VEC3', 3)],
            used=['KHR_accessor_float64'])
        mesh = _mesh(load_gltf(_glb(doc, blob)))
        assert np.allclose(np.asarray(mesh.positions).reshape(-1, 3), positions)

    def test_precise_read_keeps_double_precision(self):
        # 1e8 + 0.25 is not representable in single precision.
        data = np.array([1e8 + 0.25, 1e8 + 0.5], np.float64)
        doc = {'accessors': [_accessor(0, DOUBLE, 'SCALAR', 2)],
               'bufferViews': [{'buffer': 0, 'byteLength': data.nbytes}],
               'buffers': [{'byteLength': data.nbytes}], 'asset': {'version': '2.0'}}
        g = decode_gltf(doc)
        resolver = Resolver()
        resolver._buffers = {0: data.tobytes()}
        precise = ga._read_floats(g, 0, resolver, precise=True)
        assert precise.dtype == np.float64
        assert precise.ravel().tolist() == data.tolist()
        assert ga._read_floats(g, 0, resolver).dtype == np.float32

    def test_animation_interpolates_double_keyframes_in_double(self):
        # Two keys a quarter-second apart at t = 1e8 s, half a metre apart at
        # 1e7 m. Single precision spaces values 8 s and 1 m apart there, so it
        # would merge the keys and round the positions.
        blob = _Blob()
        pv = blob.view(TRIANGLE.astype(np.float32))
        times = np.array([1e8, 1e8 + 0.25], np.float64)
        values = np.array([[1e7, 0, 0], [1e7 + 0.5, 0, 0]], np.float64)
        tv = blob.view(times)
        vv = blob.view(values)
        accessors = [_accessor(pv, FLOAT, 'VEC3', 3),
                     _accessor(tv, DOUBLE, 'SCALAR', 2, min=[times[0]], max=[times[1]]),
                     _accessor(vv, DOUBLE, 'VEC3', 2)]
        animations = [{'samplers': [{'input': 1, 'output': 2}],
                       'channels': [{'sampler': 0,
                                     'target': {'node': 0, 'path': 'translation'}}]}]
        doc = _triangle_document(blob, {'POSITION': 0}, accessors,
                                 used=['KHR_accessor_float64'], animations=animations)
        scene = load_gltf(_glb(doc, blob))
        sampler = scene.animations[0].channels[0].sampler
        assert sampler.times.dtype == np.float64
        middle = sampler.evaluate(1e8 + 0.125)
        assert middle[0] == pytest.approx(1e7 + 0.25, abs=1e-6)


class TestQuantizedAttributes:
    """KHR_mesh_quantization: normalized integers are dequantized for every
    attribute the extension allows them on."""

    def test_normalized_short_positions_are_dequantized(self):
        blob = _Blob()
        quantized = (TRIANGLE * 32767).astype(np.int16)
        quantized = np.concatenate([quantized, np.zeros((3, 1), np.int16)], axis=1)
        view = blob.view(quantized)
        blob.views[view]['byteStride'] = 8
        acc = _accessor(view, SHORT, 'VEC3', 3, normalized=True,
                        min=[0, 0, 0], max=[32767, 32767, 0])
        doc = _triangle_document(blob, {'POSITION': 0}, [acc],
                                 used=['KHR_mesh_quantization'])
        scene = load_gltf(_glb(doc, blob))
        got = np.asarray(_mesh(scene).positions).reshape(-1, 3)
        assert np.allclose(got, TRIANGLE)
        assert scene.radius < 2.0          # framing agrees with the geometry

    def test_unnormalized_short_positions_stay_integers(self):
        blob = _Blob()
        quantized = np.concatenate([(TRIANGLE * 100).astype(np.int16),
                                    np.zeros((3, 1), np.int16)], axis=1)
        view = blob.view(quantized)
        blob.views[view]['byteStride'] = 8
        doc = _triangle_document(blob, {'POSITION': 0},
                                 [_accessor(view, SHORT, 'VEC3', 3)],
                                 used=['KHR_mesh_quantization'])
        got = np.asarray(_mesh(load_gltf(_glb(doc, blob))).positions).reshape(-1, 3)
        assert np.allclose(got, TRIANGLE * 100)

    def test_normalized_byte_normals_and_tangents(self):
        blob = _Blob()
        pv = blob.view(TRIANGLE.astype(np.float32))
        normals = np.tile(np.array([0, 0, 127, 0], np.int8), (3, 1))
        tangents = np.tile(np.array([127, 0, 0, -127], np.int8), (3, 1))
        nv = blob.view(normals)
        blob.views[nv]['byteStride'] = 4
        tv = blob.view(tangents)
        doc = _triangle_document(
            blob, {'POSITION': 0, 'NORMAL': 1, 'TANGENT': 2},
            [_accessor(pv, FLOAT, 'VEC3', 3),
             _accessor(nv, BYTE, 'VEC3', 3, normalized=True),
             _accessor(tv, BYTE, 'VEC4', 3, normalized=True)],
            used=['KHR_mesh_quantization'])
        mesh = _mesh(load_gltf(_glb(doc, blob)))
        assert np.allclose(np.asarray(mesh.normals).reshape(-1, 3), [0, 0, 1])
        assert np.allclose(np.asarray(mesh.tangents).reshape(-1, 4), [1, 0, 0, -1])

    def test_normalized_morph_target_deltas(self):
        blob = _Blob()
        pv = blob.view(TRIANGLE.astype(np.float32))
        delta = np.tile(np.array([0, 0, 64, 0], np.int8), (3, 1))
        dv = blob.view(delta)
        blob.views[dv]['byteStride'] = 4
        doc = _triangle_document(
            blob, {'POSITION': 0},
            [_accessor(pv, FLOAT, 'VEC3', 3),
             _accessor(dv, BYTE, 'VEC3', 3, normalized=True)],
            used=['KHR_mesh_quantization'], targets=[{'POSITION': 1}])
        mesh = _mesh(load_gltf(_glb(doc, blob)))
        target = mesh.morph_targets[0]['positions']
        assert np.allclose(target, [[0, 0, 64 / 127.0]] * 3)
