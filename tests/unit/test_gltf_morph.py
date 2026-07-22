"""Unit + loader tests for glTF morph-target support (no GL).

Covers the CPU deform on :class:`PBRMesh` (base + sum of weighted target deltas)
and the loader parsing ``mesh.primitives[].targets`` / default weights into a
morph-weight setter that the animation Player drives.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Animation as GAnimation, AnimationChannel, AnimationSampler,
    AnimationChannelTarget,
)

from OpenGLContext.loaders import gltf
from OpenGLContext.scenegraph.pbrmesh import PBRMesh


class TestPBRMeshMorph:
    def _mesh(self):
        base = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='f')
        t0 = np.array([[0, 0, 0], [0, 0, 1], [0, 0, 0]], dtype='f')   # move v1 +z
        t1 = np.array([[0, 0, 0], [0, 0, 0], [0, 2, 0]], dtype='f')   # move v2 +y
        return PBRMesh(positions=base, morph_targets=[{'positions': t0},
                                                      {'positions': t1}])

    def test_zero_weights_is_base(self):
        m = self._mesh()
        m.set_morph_weights([0.0, 0.0])
        assert np.allclose(m.positions, [[0, 0, 0], [1, 0, 0], [0, 1, 0]])

    def test_single_target_full_weight(self):
        m = self._mesh()
        m.set_morph_weights([1.0, 0.0])
        assert np.allclose(m.positions[1], [1, 0, 1])

    def test_blend_two_targets(self):
        m = self._mesh()
        m.set_morph_weights([0.5, 0.25])
        assert np.allclose(m.positions[1], [1, 0, 0.5])     # base + 0.5*t0
        assert np.allclose(m.positions[2], [0, 1.5, 0])     # base + 0.25*t1 (0.25*2)

    def test_reset_to_base_after_nonzero(self):
        m = self._mesh()
        m.set_morph_weights([1.0, 1.0])
        m.set_morph_weights([0.0, 0.0])
        assert np.allclose(m.positions, [[0, 0, 0], [1, 0, 0], [0, 1, 0]])

    def test_normals_morph_and_renormalize(self):
        base = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='f')
        nrm = np.array([[0, 0, 1], [0, 0, 1], [0, 0, 1]], dtype='f')
        dn = np.array([[1, 0, 0], [0, 0, 0], [0, 0, 0]], dtype='f')
        m = PBRMesh(positions=base, normals=nrm,
                    morph_targets=[{'positions': np.zeros_like(base), 'normals': dn}])
        m.set_morph_weights([1.0])
        assert np.allclose(np.linalg.norm(m.normals, axis=1), 1.0, atol=1e-5)
        assert np.allclose(m.normals[0], [1 / np.sqrt(2), 0, 1 / np.sqrt(2)], atol=1e-5)


def _pack(arrays):
    blob, spans = b"", []
    for a in arrays:
        raw = np.ascontiguousarray(a).tobytes()
        spans.append((len(blob), len(raw)))
        blob += raw
    return blob, spans


def _morph_glb(default_weights=None, animate=True):
    base = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='<f4')
    tgt = np.array([[0, 0, 0], [0, 0, 4], [0, 0, 0]], dtype='<f4')     # v1 -> +4z
    times = np.array([0.0, 1.0], dtype='<f4')
    wout = np.array([[0.0], [1.0]], dtype='<f4')                       # weight 0 -> 1
    blob, spans = _pack([base, tgt, times, wout])
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                 min=base.min(0).tolist(), max=base.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=3, type='VEC3',
                 min=tgt.min(0).tolist(), max=tgt.max(0).tolist()),
        Accessor(bufferView=2, componentType=5126, count=2, type='SCALAR',
                 min=[0.0], max=[1.0]),
        Accessor(bufferView=3, componentType=5126, count=2, type='SCALAR'),
    ]
    prim = Primitive(attributes=Attributes(POSITION=0), targets=[{'POSITION': 1}])
    mesh = Mesh(primitives=[prim])
    if default_weights is not None:
        mesh.weights = default_weights
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0, name='blob')]
    g.meshes = [mesh]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    if animate:
        g.animations = [GAnimation(
            name='morph',
            samplers=[AnimationSampler(input=2, output=3, interpolation='LINEAR')],
            channels=[AnimationChannel(
                sampler=0, target=AnimationChannelTarget(node=0, path='weights'))])]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _find_mesh(node):
    for child in getattr(node, 'children', []) or []:
        geo = getattr(child, 'geometry', None)
        if geo is not None:
            return geo
        found = _find_mesh(child)
        if found is not None:
            return found
    return None


class TestLoaderMorph:
    def test_mesh_carries_targets(self):
        scene = gltf.load_gltf(_morph_glb(animate=False))
        mesh = _find_mesh(scene.group)
        assert getattr(mesh, 'morph_targets', None)
        assert len(mesh.morph_targets) == 1

    def test_default_weights_applied(self):
        scene = gltf.load_gltf(_morph_glb(default_weights=[1.0], animate=False))
        mesh = _find_mesh(scene.group)
        assert np.allclose(mesh.positions[1], [1, 0, 4])     # fully morphed at load

    def test_weights_channel_deforms_mesh(self):
        scene = gltf.load_gltf(_morph_glb(animate=True))
        assert scene.node_morph, "loader must register a morph-weight setter"
        mesh = _find_mesh(scene.group)
        player = scene.player(0, loop=False)
        player.evaluate(0.0)
        assert np.allclose(mesh.positions[1], [1, 0, 0], atol=1e-5)
        player.evaluate(0.5)
        assert np.allclose(mesh.positions[1], [1, 0, 2], atol=1e-5)
        player.evaluate(1.0)
        assert np.allclose(mesh.positions[1], [1, 0, 4], atol=1e-5)


def _has_network():
    import urllib.request
    try:
        urllib.request.urlopen(gltf.SAMPLE_MODELS_BASE + '/README.md', timeout=6).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_network(), reason="needs network for sample models")
class TestOfficialMorphSample:
    def test_animated_morph_cube_deforms(self):
        scene = gltf.load_sample('AnimatedMorphCube')
        assert scene.node_morph, "AnimatedMorphCube must register morph setters"
        mesh = _find_mesh(scene.group)
        assert len(mesh.morph_targets) == 2
        player = scene.player(0, loop=False)
        player.evaluate(0.0)
        rest = mesh.positions.copy()
        player.evaluate(player.duration * 0.5)
        assert np.abs(rest - mesh.positions).max() > 1e-4, "morph did not deform vertices"
