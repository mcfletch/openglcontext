"""clearcoatNormalTexture.scale drawn: the coat's normal map at that strength.

A quad wearing a clearcoat whose normal map tilts the coat well off the
surface normal. At scale 0 the coat lies flat, as with no map; at scale 1 the
tilt changes what the coat reflects.
"""
import base64
import io

import numpy as np
import pytest

pytest.importorskip("pygltflib")
Image = pytest.importorskip("PIL.Image")

from OpenGLContext.loaders.gltf import load_gltf
from OpenGLContext.loaders.gltf.writer import _pack_glb
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.scenes import drawn_image, scene_context

QUAD = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], np.float32)
UV = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
INDICES = np.array([0, 1, 2, 0, 2, 3], np.uint16)


def _tilted_normal_uri():
    out = io.BytesIO()
    Image.new('RGB', (2, 2), (240, 128, 160)).save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()


def _document(scale):
    """The quad's glTF, its coat normal map at ``scale``; None for no map."""
    blob = QUAD.tobytes() + UV.tobytes() + INDICES.tobytes()
    coat = {'clearcoatFactor': 1.0, 'clearcoatRoughnessFactor': 0.0}
    if scale is not None:
        coat['clearcoatNormalTexture'] = {'index': 0, 'scale': scale}
    doc = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['KHR_materials_clearcoat'],
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                    'indices': 2, 'material': 0}]}],
        'materials': [{'pbrMetallicRoughness': {
            'baseColorFactor': [0.05, 0.05, 0.05, 1.0],
            'metallicFactor': 0.0, 'roughnessFactor': 1.0},
            'extensions': {'KHR_materials_clearcoat': coat}}],
        'textures': [{'source': 0}], 'images': [{'uri': _tilted_normal_uri()}],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 4,
             'min': [-1, -1, 0], 'max': [1, 1, 0]},
            {'bufferView': 1, 'componentType': 5126, 'type': 'VEC2', 'count': 4},
            {'bufferView': 2, 'componentType': 5123, 'type': 'SCALAR', 'count': 6}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 48},
                        {'buffer': 0, 'byteOffset': 48, 'byteLength': 32},
                        {'buffer': 0, 'byteOffset': 80, 'byteLength': 12}],
        'buffers': [{'byteLength': len(blob)}],
    }
    return _pack_glb(doc, blob)


def _drawn(scale):
    scene = load_gltf(_document(scale))
    children = [basenodes.Viewpoint(position=(0, 0, 2.5)), scene.group]
    with scene_context(children, size=(64, 64)) as context:
        drawn_image(context)
        return drawn_image(context).astype(float)[16:48, 16:48, :3]


def test_the_coat_normal_map_is_drawn_at_its_scale(gl_context):  # noqa: ARG001 the context the scenes are drawn in
    flat, unscaled, scaled = _drawn(None), _drawn(0.0), _drawn(1.0)
    assert np.abs(unscaled - flat).mean() < 1.0
    assert np.abs(scaled - flat).mean() > 4.0
