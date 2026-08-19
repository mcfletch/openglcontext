"""One asset, many instances: :func:`parse_gltf` + ``load_gltf(document=)``.

A cast of the same character or a forest of one tree loads the file many times.
A :class:`~OpenGLContext.loaders.gltf.SharedDocument` parses it once and decodes
its immutable arrays once; every build after the first references those arrays
rather than decoding its own copy, while staying an independent scenegraph. These
tests hold both halves of that bargain: the builds match a plain load, they share
the vertex data by reference, and they do not share the things an instance must
own.
"""
import json
import struct

import numpy as np
import pytest

from OpenGLContext.loaders.gltf import load_gltf, parse_gltf, SharedDocument
from OpenGLContext.loaders.gltf.scene import GLTFScene


def _meshes(scene: GLTFScene):
    """Every drawable mesh under a loaded scene's root, in build order."""
    found = []

    def walk(node):
        for child in getattr(node, 'children', None) or []:
            if hasattr(child, 'geometry') and child.geometry is not None:
                found.append(child.geometry)
            walk(child)

    walk(scene.group)
    return found


def _triangle_glb():
    """A one-triangle GLB: three positions and a float keyframe, self-contained."""
    positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='<f4')
    times = np.array([0.0, 1.0], dtype='<f4')
    blob = positions.tobytes() + times.tobytes()
    doc = {
        'asset': {'version': '2.0'},
        'scene': 0, 'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': None,
                                    'mode': 4}]}],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
             'min': [0, 0, 0], 'max': [1, 1, 0]},
            {'bufferView': 1, 'componentType': 5126, 'count': 2, 'type': 'SCALAR'},
        ],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': positions.nbytes},
            {'buffer': 0, 'byteOffset': positions.nbytes, 'byteLength': times.nbytes},
        ],
        'buffers': [{'byteLength': len(blob)}],
    }
    js = json.dumps(doc).encode('utf-8')
    js += b' ' * (-len(js) % 4)
    padded = blob + b'\x00' * (-len(blob) % 4)
    total = 12 + 8 + len(js) + 8 + len(padded)
    out = struct.pack('<III', 0x46546C67, 2, total)
    out += struct.pack('<II', len(js), 0x4E4F534A) + js
    out += struct.pack('<II', len(padded), 0x004E4942) + padded
    return out


def test_shared_document_builds_the_same_geometry_as_a_plain_load():
    data = _triangle_glb()
    document = parse_gltf(data)
    assert isinstance(document, SharedDocument)
    plain = _meshes(load_gltf(data))[0]
    shared = _meshes(load_gltf(document=document))[0]
    assert np.array_equal(plain.positions, shared.positions)


def test_instances_share_the_decoded_vertex_data():
    doc = parse_gltf(_triangle_glb())
    first = _meshes(load_gltf(document=doc))[0]
    second = _meshes(load_gltf(document=doc))[0]
    # The immutable base positions are one array both builds point at, and the
    # document remembers the decode it did so a third build would too.
    assert first.positions is second.positions
    assert doc.reads


def test_shared_vertex_data_is_read_only_so_a_deform_cannot_move_every_instance():
    doc = parse_gltf(_triangle_glb())
    positions = _meshes(load_gltf(document=doc))[0].positions
    with pytest.raises(ValueError):
        positions[0] = (9, 9, 9)


def test_instances_are_independent_scenegraphs():
    doc = parse_gltf(_triangle_glb())
    a = load_gltf(document=doc)
    b = load_gltf(document=doc)
    assert a.group is not b.group
    assert _meshes(a)[0] is not _meshes(b)[0]


def test_a_plain_load_still_decodes_writable_arrays():
    # Sharing is opt-in: a lone load hands back arrays a caller may still own and
    # deform, exactly as before.
    positions = _meshes(load_gltf(_triangle_glb()))[0].positions
    positions[0] = (5, 5, 5)          # no error: this array is this load's own
    assert tuple(positions[0]) == (5, 5, 5)


def test_load_gltf_needs_a_source_or_a_document():
    with pytest.raises(TypeError):
        load_gltf()
