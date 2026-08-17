"""The glTF loader reads EXT_mesh_gpu_instancing as one node (headless; no GL).

A thousand instances read as a thousand nodes is a thousand of everything the
render pass does per object before the batcher collapses them into the one draw
the extension is asking for. The loader builds an
:class:`~OpenGLContext.scenegraph.instancedshape.InstancedShape` instead: one
node carrying every placement.

Builds a minimal in-memory glTF -- a triangle mesh, and a node carrying three
instance TRANSLATIONs through the extension -- and asserts what comes back.
"""
import base64
import json

import numpy as np

from OpenGLContext.loaders import gltf
from OpenGLContext.scenegraph.instancedshape import InstancedShape
from OpenGLContext.scenegraph.shape import Shape


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


def _loaded(tmp_path, translations, name='inst.gltf'):
    path = tmp_path / name
    path.write_text(json.dumps(_minimal_instanced_gltf(translations)))
    scene = gltf.load_gltf(str(path))
    nodes = []
    _flatten(scene.group, nodes)
    return nodes


TRANSLATIONS = [(-2, 0, 0), (0, 0, 0), (2, 0, 0)]


class TestWhatTheLoaderBuilds:
    def test_the_instances_are_one_node(self, tmp_path) -> None:
        nodes = _loaded(tmp_path, TRANSLATIONS)
        placed = [n for n in nodes if isinstance(n, InstancedShape)]
        assert len(placed) == 1

    def test_no_other_shape_is_left_behind(self, tmp_path) -> None:
        """The mesh draws through the placements, not beside them."""
        nodes = _loaded(tmp_path, TRANSLATIONS)
        assert [n for n in nodes if isinstance(n, Shape)
                and not isinstance(n, InstancedShape)] == []

    def test_it_holds_every_instance(self, tmp_path) -> None:
        nodes = _loaded(tmp_path, TRANSLATIONS)
        placed = [n for n in nodes if isinstance(n, InstancedShape)][0]
        assert len(placed.instancePlacements()) == 3

    def test_the_placements_are_the_translations(self, tmp_path) -> None:
        nodes = _loaded(tmp_path, TRANSLATIONS)
        placed = [n for n in nodes if isinstance(n, InstancedShape)][0]
        got = sorted(tuple(round(float(v), 3) for v in matrix[3, :3])
                     for matrix in placed.instancePlacements())
        assert got == sorted(tuple(float(v) for v in t) for t in TRANSLATIONS)

    def test_it_carries_the_mesh_geometry(self, tmp_path) -> None:
        nodes = _loaded(tmp_path, TRANSLATIONS)
        placed = [n for n in nodes if isinstance(n, InstancedShape)][0]
        assert placed.geometry is not None
        assert len(placed.geometry.positions) == 3

    def test_two_such_nodes_share_one_geometry(self, tmp_path) -> None:
        """What lets tiles of the same forest batch into one draw."""
        first = _loaded(tmp_path, TRANSLATIONS, 'a.gltf')
        second = _loaded(tmp_path, TRANSLATIONS, 'b.gltf')
        from OpenGLContext.passes.instancing import geometry_content_key
        keys = [geometry_content_key([n]) for nodes in (first, second)
                for n in nodes if isinstance(n, InstancedShape)]
        assert keys[0][0] == keys[1][0]

    def test_the_bounds_cover_the_whole_set(self, tmp_path) -> None:
        nodes = _loaded(tmp_path, TRANSLATIONS)
        placed = [n for n in nodes if isinstance(n, InstancedShape)][0]
        points = np.asarray(placed.boundingVolume(None).getPoints())
        assert points[:, 0].min() <= -2.0
        assert points[:, 0].max() >= 2.0

    def test_the_scene_is_framed_around_all_of_them(self, tmp_path) -> None:
        """The framing radius is what a viewer opens on."""
        path = tmp_path / 'framed.gltf'
        path.write_text(json.dumps(_minimal_instanced_gltf(TRANSLATIONS)))
        scene = gltf.load_gltf(str(path))
        assert scene.radius >= 2.0
        assert abs(float(scene.center[0])) < 1.0


def test_an_extension_naming_no_attributes_draws_the_mesh_once(tmp_path) -> None:
    doc = _minimal_instanced_gltf(TRANSLATIONS)
    doc['nodes'][0]['extensions']['EXT_mesh_gpu_instancing'] = {}
    path = tmp_path / 'empty.gltf'
    path.write_text(json.dumps(doc))
    nodes = []
    _flatten(gltf.load_gltf(str(path)).group, nodes)
    assert [n for n in nodes if isinstance(n, InstancedShape)] == []
    assert len([n for n in nodes if isinstance(n, Shape)]) == 1
