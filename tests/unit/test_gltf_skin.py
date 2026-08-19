"""Unit + loader tests for glTF skinning (linear-blend, CPU, no GL).

Covers the LBS deform on :class:`PBRMesh` (skin matrices + joints/weights), the
:class:`Skin` joint-matrix assembly from animated joint world transforms, and the
loader parsing ``skins`` / ``JOINTS_0`` / ``WEIGHTS_0`` / ``inverseBindMatrices``.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Skin, Animation as GAnimation, AnimationChannel, AnimationSampler,
    AnimationChannelTarget,
)

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import animation as ga
from OpenGLContext.scenegraph.pbrmesh import PBRMesh


def _rot_z_rowvec(theta):
    """Row-vector rotation about +Z (p' = p @ M)."""
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, s, 0, 0], [-s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype='d')


class TestPBRMeshSkin:
    def _mesh(self):
        pos = np.array([[1, 0, 0], [0, 1, 0]], dtype='f')
        joints = np.array([[0, 0, 0, 0], [1, 0, 0, 0]], dtype='u4')
        weights = np.array([[1, 0, 0, 0], [1, 0, 0, 0]], dtype='f')
        return PBRMesh(positions=pos, skin_joints=joints, skin_weights=weights)

    def test_identity_matrices_are_bind_pose(self):
        m = self._mesh()
        ident = np.stack([np.eye(4), np.eye(4)])
        m.set_skin_matrices(ident)
        assert np.allclose(m.positions, [[1, 0, 0], [0, 1, 0]])

    def test_joint_rotation_moves_bound_vertex(self):
        m = self._mesh()
        # vertex 0 is fully bound to joint 0; rotate joint 0 by +90deg about Z
        mats = np.stack([_rot_z_rowvec(np.pi / 2), np.eye(4)])
        m.set_skin_matrices(mats)
        # Where the pose puts the vertex, whichever side does the skinning: the
        # vertex arrays of a mesh the shader skins hold the rest pose all the
        # way through, so the posed positions are asked for rather than read off.
        posed = m.posed_positions()
        assert np.allclose(posed[0], [0, 1, 0], atol=1e-6)   # (1,0,0)->(0,1,0)
        assert np.allclose(posed[1], [0, 1, 0], atol=1e-6)   # joint1 identity

    def test_weight_blend_between_two_joints(self):
        pos = np.array([[1, 0, 0]], dtype='f')
        joints = np.array([[0, 1, 0, 0]], dtype='u4')
        weights = np.array([[0.5, 0.5, 0, 0]], dtype='f')
        m = PBRMesh(positions=pos, skin_joints=joints, skin_weights=weights)
        # joint0 identity, joint1 translates +2 in x (row-vector translation row 3)
        t = np.eye(4)
        t[3, 0] = 2.0
        m.set_skin_matrices(np.stack([np.eye(4), t]))
        # 0.5*(1,0,0) + 0.5*(3,0,0) = (2,0,0)
        assert np.allclose(m.posed_positions()[0], [2, 0, 0], atol=1e-6)

    def test_unnormalized_weights_are_normalized(self):
        pos = np.array([[1, 0, 0]], dtype='f')
        joints = np.array([[0, 1, 0, 0]], dtype='u4')
        weights = np.array([[1.0, 1.0, 0, 0]], dtype='f')      # sum 2 -> normalize
        m = PBRMesh(positions=pos, skin_joints=joints, skin_weights=weights)
        t = np.eye(4)
        t[3, 0] = 2.0
        m.set_skin_matrices(np.stack([np.eye(4), t]))
        assert np.allclose(m.posed_positions()[0], [2, 0, 0], atol=1e-6)


class TestSkinAssembly:
    def test_bind_pose_is_identity_transform(self):
        # one joint at origin; inverse bind = identity; mesh node identity
        mesh = PBRMesh(positions=np.array([[1, 0, 0]], 'f'),
                       skin_joints=np.array([[0, 0, 0, 0]], 'u4'),
                       skin_weights=np.array([[1, 0, 0, 0]], 'f'))
        inv_bind = np.stack([np.eye(4)])
        worlds = {0: np.eye(4), 1: np.eye(4)}   # node 0 mesh, node 1 joint
        skin = ga.Skin(joints=[1], inverse_bind=inv_bind, mesh_node=0, meshes=[mesh])
        skin.apply(worlds)
        assert np.allclose(mesh.positions, [[1, 0, 0]])

    def test_rotated_joint_deforms(self):
        mesh = PBRMesh(positions=np.array([[1, 0, 0]], 'f'),
                       skin_joints=np.array([[0, 0, 0, 0]], 'u4'),
                       skin_weights=np.array([[1, 0, 0, 0]], 'f'))
        inv_bind = np.stack([np.eye(4)])
        worlds = {0: np.eye(4), 1: _rot_z_rowvec(np.pi / 2)}
        skin = ga.Skin(joints=[1], inverse_bind=inv_bind, mesh_node=0, meshes=[mesh])
        skin.apply(worlds)
        assert np.allclose(mesh.posed_positions()[0], [0, 1, 0], atol=1e-6)


def _pack(arrays):
    blob, spans = b"", []
    for a in arrays:
        raw = np.ascontiguousarray(a).tobytes()
        spans.append((len(blob), len(raw)))
        blob += raw
    return blob, spans


def _skinned_glb():
    """Two-vertex bar skinned to two joints; joint 1 rotates 90deg about Z over 1s.

    node 0: skinned mesh (skin 0). node 1: joint A (root of skeleton). node 2:
    joint B, child of node 1, animated.
    """
    pos = np.array([[0, 0, 0], [1, 0, 0]], dtype='<f4')
    joints = np.array([[0, 0, 0, 0], [1, 0, 0, 0]], dtype='<u2')   # v0->jA, v1->jB
    weights = np.array([[1, 0, 0, 0], [1, 0, 0, 0]], dtype='<f4')
    ibm = np.stack([np.eye(4), np.eye(4)]).astype('<f4')           # bind at origin
    times = np.array([0.0, 1.0], dtype='<f4')
    a = np.pi / 2
    rot = np.array([[0, 0, 0, 1], [0, 0, np.sin(a / 2), np.cos(a / 2)]], dtype='<f4')

    blob, spans = _pack([pos, joints, weights, ibm, times, rot])
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=2, type='VEC3',
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),          # 0 POSITION
        Accessor(bufferView=1, componentType=5123, count=2, type='VEC4'),    # 1 JOINTS_0 (ushort)
        Accessor(bufferView=2, componentType=5126, count=2, type='VEC4'),    # 2 WEIGHTS_0
        Accessor(bufferView=3, componentType=5126, count=2, type='MAT4'),    # 3 inverseBind
        Accessor(bufferView=4, componentType=5126, count=2, type='SCALAR',
                 min=[0.0], max=[1.0]),                                       # 4 time
        Accessor(bufferView=5, componentType=5126, count=2, type='VEC4'),    # 5 rotation
    ]
    prim = Primitive(attributes=Attributes(POSITION=0, JOINTS_0=1, WEIGHTS_0=2))
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0, 1])]
    g.nodes = [
        Node(mesh=0, skin=0, name='skinned'),        # 0
        Node(children=[2], name='jointA'),           # 1
        Node(name='jointB'),                         # 2
    ]
    g.meshes = [Mesh(primitives=[prim])]
    g.skins = [Skin(joints=[1, 2], inverseBindMatrices=3, skeleton=1)]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = [GAnimation(
        name='bend',
        samplers=[AnimationSampler(input=4, output=5, interpolation='LINEAR')],
        channels=[AnimationChannel(
            sampler=0, target=AnimationChannelTarget(node=2, path='rotation'))])]
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


class TestLoaderSkin:
    def test_mesh_carries_skin_attributes(self):
        scene = gltf.load_gltf(_skinned_glb())
        mesh = _find_mesh(scene.group)
        assert mesh.skin_joints is not None and mesh.skin_weights is not None
        assert mesh.skin_joints.shape == (2, 4)

    def test_scene_exposes_skins(self):
        scene = gltf.load_gltf(_skinned_glb())
        assert getattr(scene, 'skins', None), "loader must expose skins"
        assert len(scene.skins) == 1

    def test_animation_bends_skinned_mesh(self):
        scene = gltf.load_gltf(_skinned_glb())
        mesh = _find_mesh(scene.group)
        player = scene.player(0, loop=False)
        player.evaluate(0.0)
        assert np.allclose(mesh.posed_positions()[1], [1, 0, 0], atol=1e-5)  # bind pose
        player.evaluate(1.0)
        # jointB (node 2) rotated 90deg about Z; vertex 1 bound to it -> (0,1,0)
        posed = mesh.posed_positions()
        assert np.allclose(posed[1], [0, 1, 0], atol=1e-4)
        assert np.allclose(posed[0], [0, 0, 0], atol=1e-5)   # vertex 0 at jointA


class TestSceneNodeAccess:
    """What a consumer needs to read a document's own structure back.

    The hierarchy, the names and the document extensions: everything the
    character layer resolves a skeleton and an attachment point from.
    """

    def test_hierarchy_and_names(self):
        scene = gltf.load_gltf(_skinned_glb())
        assert scene.node_roots == [0, 1]
        assert scene.node_children[1] == [2]
        assert scene.node_names[2] == 'jointB'

    def test_a_document_with_no_extensions(self):
        scene = gltf.load_gltf(_skinned_glb())
        assert scene.extensions == {}

    def test_unnamed_nodes_are_simply_absent(self):
        scene = gltf.load_gltf(_skinned_glb())
        assert set(scene.node_names) == {0, 1, 2}
