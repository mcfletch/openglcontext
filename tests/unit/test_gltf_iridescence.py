"""KHR_materials_iridescence: loader parse + material fields + UBO packing.

Thin-film iridescence (IridescenceLamp / IridescenceMetallicSpheres /
IridescenceSuzanne). Loader-level tests (no GL) plus the std140 packing of the
iridescence factors into the material block.
"""
import json

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.loaders import gltf
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


def _tri_gltf_with_material(material_ext):
    import base64
    pos = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], '<f4')
    blob = pos.tobytes()
    uri = 'data:application/octet-stream;base64,' + base64.b64encode(blob).decode()
    return {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['KHR_materials_iridescence'],
        'buffers': [{'byteLength': len(blob), 'uri': uri}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(blob)}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3,
                       'type': 'VEC3', 'min': [0, 0, 0], 'max': [1, 1, 0]}],
        'materials': [{'pbrMetallicRoughness': {'baseColorFactor': [1, 1, 1, 1]},
                       'extensions': {'KHR_materials_iridescence': material_ext}}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'material': 0}]}],
        'nodes': [{'mesh': 0}],
        'scenes': [{'nodes': [0]}],
        'scene': 0,
    }


def _material_of(doc):
    scene = gltf.load_gltf(json.dumps(doc).encode('utf-8'))
    out = []

    def find(n):
        ap = getattr(n, 'appearance', None)
        if ap is not None and getattr(ap, 'material', None) is not None:
            out.append(ap.material)
        for c in getattr(n, 'children', []) or []:
            find(c)
    find(scene.group)
    return out[0]


class TestIridescenceParse:
    def test_factor_and_ior(self):
        mat = _material_of(_tri_gltf_with_material({
            'iridescenceFactor': 0.8, 'iridescenceIor': 1.8}))
        assert isinstance(mat, PBRMaterial)
        assert abs(mat.iridescence - 0.8) < 1e-6
        assert abs(mat.iridescenceIor - 1.8) < 1e-6

    def test_thickness_defaults(self):
        # spec defaults: min 100nm, max 400nm
        mat = _material_of(_tri_gltf_with_material({'iridescenceFactor': 1.0}))
        assert abs(mat.iridescenceThicknessMin - 100.0) < 1e-3
        assert abs(mat.iridescenceThicknessMax - 400.0) < 1e-3

    def test_thickness_range(self):
        mat = _material_of(_tri_gltf_with_material({
            'iridescenceFactor': 1.0,
            'iridescenceThicknessMinimum': 200.0,
            'iridescenceThicknessMaximum': 800.0}))
        assert abs(mat.iridescenceThicknessMin - 200.0) < 1e-3
        assert abs(mat.iridescenceThicknessMax - 800.0) < 1e-3

    def test_absent_extension_is_zero(self):
        mat = _material_of({
            'asset': {'version': '2.0'},
            'materials': [{'pbrMetallicRoughness': {'baseColorFactor': [1, 1, 1, 1]}}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'material': 0}]}],
            'buffers': [{'byteLength': 36,
                         'uri': 'data:application/octet-stream;base64,' +
                         __import__('base64').b64encode(
                             np.zeros((3, 3), '<f4').tobytes()).decode()}],
            'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3,
                           'type': 'VEC3', 'min': [0, 0, 0], 'max': [0, 0, 0]}],
            'nodes': [{'mesh': 0}], 'scenes': [{'nodes': [0]}], 'scene': 0,
        })
        assert mat.iridescence == 0.0


class TestIridescenceUBO:
    def test_packed_into_material_block(self):
        from OpenGLContext.passes.pbrpass import pack_material_block, MATERIAL_BLOCK_WORDS
        mat = PBRMaterial(baseColor=(1, 1, 1))
        mat.iridescence = 0.5
        mat.iridescenceIor = 1.7
        mat.iridescenceThicknessMin = 150.0
        mat.iridescenceThicknessMax = 600.0
        buf = pack_material_block(mat)
        # the iridescence vec4 lives just past the uvTransform mat3 (words 44..47)
        assert len(buf) >= 48
        assert abs(buf[44] - 0.5) < 1e-5
        assert abs(buf[45] - 1.7) < 1e-5
        assert abs(buf[46] - 150.0) < 1e-3
        assert abs(buf[47] - 600.0) < 1e-3
