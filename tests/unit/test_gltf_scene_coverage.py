"""Coverage tests for the glTF scene-assembly helpers.

``GLTFScene`` DEF lookup / player guards, the digit-prefixed DEF token, the
EXT_mesh_gpu_instancing translation/rotation/scale expansion, the single-camera
back-compat helper, and the non-dict light guard. Pure numpy, no GL.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
from pygltflib import Accessor, BufferView, Buffer  # noqa: E402

from OpenGLContext.loaders.gltf import scene as gs  # noqa: E402
from OpenGLContext.loaders.gltf.scene import GLTFScene  # noqa: E402


class _R:
    def __init__(self, data):
        self._buffers = {0: data}


class TestGLTFSceneAccessors:
    def test_get_def_without_scenegraph_is_none(self):
        sc = GLTFScene(group=None, center=(0, 0, 0), radius=1.0)
        assert sc.getDEF('anything') is None

    def test_get_def_delegates_to_scenegraph(self):
        from OpenGLContext.scenegraph.scenegraph import SceneGraph
        from OpenGLContext.scenegraph.basenodes import Transform
        sg = SceneGraph()
        marker = Transform()
        sg.regDefName('Hero', marker)
        sc = GLTFScene(group=None, center=(0, 0, 0), radius=1.0, sceneGraph=sg)
        assert sc.getDEF('Hero') is marker

    def test_player_none_without_animations(self):
        sc = GLTFScene(group=None, center=(0, 0, 0), radius=1.0)
        assert sc.player(0) is None

    def test_player_none_for_out_of_range_index(self):
        sc = GLTFScene(group=None, center=(0, 0, 0), radius=1.0, animations=['a'])
        assert sc.player(5) is None


class TestDefName:
    def test_digit_leading_name_is_prefixed(self):
        # VRML DEF tokens may not start with a digit, so a leading digit is escaped.
        assert gs._def_name('7up', 0) == '_7up'

    def test_empty_name_falls_back_to_index(self):
        assert gs._def_name('   ', 4) == 'node4'


class TestGpuInstanceTransforms:
    def test_translation_rotation_scale_applied_per_instance(self):
        trans = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        # two 90deg-about-Y quaternions (identical) as VEC4 xyzw
        s = np.sin(np.pi / 4)
        rot = np.array([[0, s, 0, s], [0, s, 0, s]], dtype=np.float32)
        scale = np.array([[2, 2, 2], [0.5, 0.5, 0.5]], dtype=np.float32)
        blob = trans.tobytes() + rot.tobytes() + scale.tobytes()
        g = pygltflib.GLTF2()
        g.accessors = [
            Accessor(bufferView=0, componentType=5126, count=2, type='VEC3'),
            Accessor(bufferView=1, componentType=5126, count=2, type='VEC4'),
            Accessor(bufferView=2, componentType=5126, count=2, type='VEC3'),
        ]
        g.bufferViews = [
            BufferView(buffer=0, byteOffset=0, byteLength=trans.nbytes),
            BufferView(buffer=0, byteOffset=trans.nbytes, byteLength=rot.nbytes),
            BufferView(buffer=0, byteOffset=trans.nbytes + rot.nbytes,
                       byteLength=scale.nbytes),
        ]
        g.buffers = [Buffer(byteLength=len(blob))]
        ext = {'attributes': {'TRANSLATION': 0, 'ROTATION': 1, 'SCALE': 2}}
        out = gs.gpu_instance_placements(g, ext, _R(blob))
        assert out.shape == (2, 4, 4)
        assert np.allclose(out[0][3, :3], [1, 2, 3])
        # the second instance is scaled by a half and turned a quarter turn
        # about +Y, which takes +X to -Z
        point = np.array([1.0, 0, 0, 1.0]) @ out[1]
        assert np.allclose(point[:3], [4, 5, 5.5], atol=1e-4)

    def test_no_attributes_yields_nothing(self):
        assert gs.gpu_instance_placements(pygltflib.GLTF2(), {}, _R(b'')) is None


class TestCameraPoseHelper:
    def test_first_pose_returned(self):
        cam = pygltflib.Camera(type='perspective',
                               perspective=pygltflib.Perspective(yfov=0.5, znear=0.1))
        pose = gs._camera_pose([(np.eye(4), cam)])
        assert pose is not None and round(pose['fov'], 2) == 0.5

    def test_none_when_no_cameras(self):
        assert gs._camera_pose([]) is None


class TestLightNodeGuard:
    def test_non_dict_light_def_is_none(self):
        assert gs._light_node("not-a-dict", np.eye(4)) is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
