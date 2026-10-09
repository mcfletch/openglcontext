"""Two loader behaviours a document relies on without saying so.

A document's ``extensionsRequired`` names what it cannot be read without; one
this loader does not read is reported. A primitive whose material samples a
direction in tangent space (a normal map, an anisotropy map, a clearcoat
normal map) and ships no ``TANGENT`` is given tangents.
"""
import base64
import io

import numpy as np
import pytest

pytest.importorskip("pygltflib")
Image = pytest.importorskip("PIL.Image")

from OpenGLContext.loaders.gltf import load_gltf
from OpenGLContext.loaders.gltf.loader import SUPPORTED_EXTENSIONS
from OpenGLContext.loaders.gltf.writer import _pack_glb

TRIANGLE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
UV = np.array([[0, 0], [1, 0], [0, 1]], np.float32)


def _png_uri():
    out = io.BytesIO()
    Image.new('RGB', (2, 2), (128, 128, 255)).save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()


def _document(material=None, required=()):
    blob = TRIANGLE.tobytes() + UV.tobytes()
    doc = {
        'asset': {'version': '2.0'},
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                    'material': 0}]}],
        'materials': [material or {}],
        'textures': [{'source': 0}], 'images': [{'uri': _png_uri()}],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 3,
             'min': [0, 0, 0], 'max': [1, 1, 0]},
            {'bufferView': 1, 'componentType': 5126, 'type': 'VEC2', 'count': 3}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36},
                        {'buffer': 0, 'byteOffset': 36, 'byteLength': 24}],
        'buffers': [{'byteLength': len(blob)}],
    }
    if required:
        doc['extensionsUsed'] = list(required)
        doc['extensionsRequired'] = list(required)
    return _pack_glb(doc, blob)


def _mesh(scene):
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            return node.geometry
        stack.extend(getattr(node, 'children', None) or [])
    raise AssertionError('no shape')


class TestRequired:
    def test_an_unread_required_extension_is_reported(self, caplog):
        load_gltf(_document(required=['EXT_made_up', 'EXT_made_up_too']))
        assert 'EXT_made_up_too' in caplog.text and 'EXT_made_up' in caplog.text

    def test_a_read_required_extension_is_not(self, caplog):
        load_gltf(_document(required=['KHR_mesh_quantization', 'KHR_meshopt_compression']))
        assert 'extensionsRequired' not in caplog.text

    @pytest.mark.parametrize('name', [
        'KHR_accessor_float16', 'KHR_accessor_float64', 'KHR_materials_variants',
        'KHR_meshopt_compression', 'EXT_meshopt_compression', 'EXT_texture_avif',
        'KHR_draco_mesh_compression', 'KHR_animation_pointer', 'KHR_node_visibility',
        'KHR_texture_basisu'])
    def test_the_list_holds_what_the_loader_reads(self, name):
        assert name in SUPPORTED_EXTENSIONS


class TestTangents:
    @pytest.mark.parametrize('material', [
        {'normalTexture': {'index': 0}},
        {'extensions': {'KHR_materials_anisotropy': {
            'anisotropyStrength': 1.0, 'anisotropyTexture': {'index': 0}}}},
        {'extensions': {'KHR_materials_anisotropy': {'anisotropyStrength': 1.0}}},
        {'extensions': {'KHR_materials_clearcoat': {
            'clearcoatFactor': 1.0, 'clearcoatNormalTexture': {'index': 0}}}},
    ], ids=['normal map', 'anisotropy map', 'anisotropy', 'clearcoat normal map'])
    def test_tangents_are_made_where_the_material_needs_them(self, material):
        tangents = _mesh(load_gltf(_document(material))).tangents
        assert tangents is not None
        assert np.allclose(tangents[:, :3], [1, 0, 0])

    def test_no_tangents_where_nothing_reads_them(self):
        assert _mesh(load_gltf(_document({}))).tangents is None
