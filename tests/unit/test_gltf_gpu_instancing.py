"""Stage 4: the glTF loader expands EXT_mesh_gpu_instancing into per-instance
Transforms sharing one mesh (headless; no GL).

Builds a minimal in-memory glTF (a triangle mesh + a node carrying three instance
TRANSLATIONs via the extension), loads it, and asserts the scene contains three
instance transforms that all reference the SAME shared mesh shape at the three
translations -- exactly what the instancing draw path then collapses.
"""
import base64
import json
import struct

import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.scenegraph.transform import Transform


def _b64(data: bytes) -> str:
    return 'data:application/octet-stream;base64,' + base64.b64encode(data).decode('ascii')


def _minimal_instanced_gltf(translations):
    positions = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype='<f4')
    trans = np.asarray(translations, dtype='<f4')
    blob = positions.tobytes() + trans.tobytes()
    pos_len = positions.nbytes
    return {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['EXT_mesh_gpu_instancing'],
        'buffers': [{'byteLength': len(blob), 'uri': _b64(blob)}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': pos_len},
            {'buffer': 0, 'byteOffset': pos_len, 'byteLength': trans.nbytes},
        ],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
             'min': [0, 0, 0], 'max': [1, 1, 0]},
            {'bufferView': 1, 'componentType': 5126, 'count': len(trans), 'type': 'VEC3'},
        ],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
        'nodes': [{
            'mesh': 0,
            'extensions': {'EXT_mesh_gpu_instancing': {'attributes': {'TRANSLATION': 1}}},
        }],
        'scenes': [{'nodes': [0]}],
        'scene': 0,
    }


def _flatten(node, out):
    out.append(node)
    for c in getattr(node, 'children', None) or []:
        _flatten(c, out)


def test_ext_mesh_gpu_instancing_expands_to_instances(tmp_path):
    translations = [(-2, 0, 0), (0, 0, 0), (2, 0, 0)]
    path = tmp_path / 'inst.gltf'
    path.write_text(json.dumps(_minimal_instanced_gltf(translations)))

    scene = gltf.load_gltf(str(path))

    nodes = []
    _flatten(scene.group, nodes)
    # Collect the shapes and the transforms that directly parent a shape.
    from OpenGLContext.scenegraph.shape import Shape
    shapes = [n for n in nodes if isinstance(n, Shape)]
    # One shared mesh shape, referenced by three instance transforms.
    assert len(shapes) >= 1
    instance_transforms = [
        n for n in nodes
        if isinstance(n, Transform)
        and any(isinstance(c, Shape) for c in (getattr(n, 'children', None) or []))
    ]
    assert len(instance_transforms) == 3, (
        'expected 3 instance transforms, got %d' % len(instance_transforms))

    # The three instances carry the three translations (order-independent).
    got = sorted(tuple(round(float(v), 3) for v in t.translation)
                 for t in instance_transforms)
    assert got == sorted(tuple(float(v) for v in tr) for tr in translations)

    # All instances share ONE mesh shape object (mesh_cache), so the instancing
    # path can collapse them.
    shared = set()
    for t in instance_transforms:
        for c in t.children:
            if isinstance(c, Shape):
                shared.add(id(c))
    assert len(shared) == 1, 'instances must share one mesh shape, saw %d' % len(shared)
