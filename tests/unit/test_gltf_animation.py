"""Unit tests for the glTF keyframe animation core (interpolation math + binding).

Pure Python/numpy -- no GL, no network. Exercises the STEP/LINEAR/CUBICSPLINE
sampler evaluation, quaternion slerp, morph-weight channels and the binding of
channels onto scenegraph Transform nodes.
"""
import math

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.loaders.gltf import animation as ga


# --------------------------------------------------------------------------
# Sampler interpolation
# --------------------------------------------------------------------------

class TestSamplerStep:
    def test_holds_previous_keyframe(self):
        s = ga.Sampler(
            times=np.array([0.0, 1.0, 2.0]),
            values=np.array([[0.0], [10.0], [20.0]]),
            interpolation='STEP')
        assert s.evaluate(0.0)[0] == 0.0
        assert s.evaluate(0.99)[0] == 0.0     # holds the earlier key
        assert s.evaluate(1.0)[0] == 10.0
        assert s.evaluate(1.5)[0] == 10.0
        assert s.evaluate(2.0)[0] == 20.0


class TestSamplerLinear:
    def test_midpoint_translation(self):
        s = ga.Sampler(
            times=np.array([0.0, 2.0]),
            values=np.array([[0.0, 0.0, 0.0], [10.0, -4.0, 2.0]]),
            interpolation='LINEAR')
        mid = s.evaluate(1.0)
        assert np.allclose(mid, [5.0, -2.0, 1.0])

    def test_exact_keyframe(self):
        s = ga.Sampler(
            times=np.array([0.0, 1.0, 3.0]),
            values=np.array([[1.0], [2.0], [8.0]]),
            interpolation='LINEAR')
        assert math.isclose(s.evaluate(1.0)[0], 2.0)
        # 1/3 of the way through the 1->3 segment
        assert math.isclose(s.evaluate(1.0 + (3.0 - 1.0) / 3.0)[0], 2.0 + (8.0 - 2.0) / 3.0)


class TestSamplerClamp:
    def test_clamps_before_and_after(self):
        s = ga.Sampler(
            times=np.array([1.0, 2.0]),
            values=np.array([[5.0], [7.0]]),
            interpolation='LINEAR')
        assert s.evaluate(-100.0)[0] == 5.0     # before first key -> first value
        assert s.evaluate(100.0)[0] == 7.0      # after last key -> last value

    def test_single_keyframe(self):
        s = ga.Sampler(times=np.array([4.0]), values=np.array([[3.0, 3.0]]),
                       interpolation='LINEAR')
        assert np.allclose(s.evaluate(0.0), [3.0, 3.0])
        assert np.allclose(s.evaluate(99.0), [3.0, 3.0])


class TestSamplerRotationSlerp:
    def test_slerp_stays_unit_and_halfway(self):
        # 0deg and 90deg about +Y, both as glTF [x,y,z,w] quaternions
        q0 = [0.0, 0.0, 0.0, 1.0]
        a = math.radians(90.0)
        q1 = [0.0, math.sin(a / 2), 0.0, math.cos(a / 2)]
        s = ga.Sampler(times=np.array([0.0, 1.0]),
                       values=np.array([q0, q1]),
                       interpolation='LINEAR', is_rotation=True)
        mid = s.evaluate(0.5)
        assert math.isclose(np.linalg.norm(mid), 1.0, rel_tol=1e-6)
        # slerp halfway between 0 and 90 deg about Y is 45 deg about Y
        b = math.radians(45.0)
        expected = np.array([0.0, math.sin(b / 2), 0.0, math.cos(b / 2)])
        # allow sign ambiguity of quaternions
        assert (np.allclose(mid, expected, atol=1e-5)
                or np.allclose(mid, -expected, atol=1e-5))


class TestSamplerCubicSpline:
    def test_endpoints_equal_keyframe_values(self):
        # output layout per key: [inTangent, value, outTangent]
        keys = np.array([
            [0.0], [0.0], [0.0],      # key0: value 0
            [0.0], [10.0], [0.0],     # key1: value 10
        ])
        s = ga.Sampler(times=np.array([0.0, 1.0]), values=keys,
                       interpolation='CUBICSPLINE')
        assert math.isclose(s.evaluate(0.0)[0], 0.0, abs_tol=1e-9)
        assert math.isclose(s.evaluate(1.0)[0], 10.0, abs_tol=1e-9)

    def test_flat_tangents_are_smoothstep(self):
        keys = np.array([[0.0], [0.0], [0.0], [0.0], [1.0], [0.0]])
        s = ga.Sampler(times=np.array([0.0, 1.0]), values=keys,
                       interpolation='CUBICSPLINE')
        # zero tangents -> Hermite reduces to smoothstep 3u^2-2u^3; at u=0.5 -> 0.5
        assert math.isclose(s.evaluate(0.5)[0], 0.5, abs_tol=1e-9)


class TestDuration:
    def test_duration_is_last_input_time(self):
        s = ga.Sampler(times=np.array([0.0, 1.5, 4.0]),
                       values=np.array([[0.0], [1.0], [2.0]]),
                       interpolation='STEP')
        assert math.isclose(s.duration, 4.0)


# --------------------------------------------------------------------------
# Quaternion -> VRML axis-angle
# --------------------------------------------------------------------------

class TestQuatToAxisAngle:
    def test_identity(self):
        x, y, z, r = ga.quat_xyzw_to_vrml([0.0, 0.0, 0.0, 1.0])
        assert math.isclose(r, 0.0, abs_tol=1e-6)

    def test_ninety_about_y(self):
        a = math.radians(90.0)
        q = [0.0, math.sin(a / 2), 0.0, math.cos(a / 2)]
        x, y, z, r = ga.quat_xyzw_to_vrml(q)
        assert math.isclose(abs(y), 1.0, abs_tol=1e-6)
        assert math.isclose(r, a, abs_tol=1e-6)


# --------------------------------------------------------------------------
# Loader integration: animations parsed from a synthetic GLB drive Transforms
# --------------------------------------------------------------------------

from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Animation as GAnimation, AnimationChannel, AnimationSampler,
    AnimationChannelTarget,
)

from OpenGLContext.loaders import gltf


def _pack(arrays):
    """Concatenate arrays into one blob; return (blob, [(offset, nbytes)...])."""
    blob = b""
    spans = []
    for a in arrays:
        b = np.ascontiguousarray(a).tobytes()
        spans.append((len(blob), len(b)))
        blob += b
    return blob, spans


def _animated_translation_glb(interp='LINEAR'):
    """A single triangle node whose translation animates (0,0,0)->(5,0,0) over 1s."""
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    times = np.array([0.0, 1.0], dtype=np.float32)
    if interp == 'CUBICSPLINE':
        # per key: in-tangent, value, out-tangent
        out = np.array([[0, 0, 0], [0, 0, 0], [0, 0, 0],
                        [0, 0, 0], [5, 0, 0], [0, 0, 0]], dtype=np.float32)
    else:
        out = np.array([[0, 0, 0], [5, 0, 0]], dtype=np.float32)

    blob, spans = _pack([pos, times, out])
    views = [BufferView(buffer=0, byteOffset=o, byteLength=n) for (o, n) in spans]
    accessors = [
        Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                 max=pos.max(0).tolist(), min=pos.min(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(times), type='SCALAR',
                 max=[float(times.max())], min=[float(times.min())]),
        Accessor(bufferView=2, componentType=5126, count=len(out), type='VEC3'),
    ]
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0, name='mover')]
    g.meshes = [Mesh(primitives=[Primitive(attributes=Attributes(POSITION=0))])]
    g.accessors = accessors
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = [GAnimation(
        name='move',
        samplers=[AnimationSampler(input=1, output=2, interpolation=interp)],
        channels=[AnimationChannel(
            sampler=0, target=AnimationChannelTarget(node=0, path='translation'))],
    )]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


class TestLoaderAnimation:
    def test_scene_exposes_animation(self):
        scene = gltf.load_gltf(_animated_translation_glb())
        assert len(scene.animations) == 1
        assert math.isclose(scene.animations[0].duration, 1.0)
        assert scene.node_transforms  # node index -> Transform map is populated

    def test_player_drives_transform_translation(self):
        scene = gltf.load_gltf(_animated_translation_glb())
        player = scene.player(0, loop=False)
        xform = scene.node_transforms[0]
        player.evaluate(0.0)
        assert np.allclose(xform.translation, [0, 0, 0], atol=1e-5)
        player.evaluate(0.5)
        assert np.allclose(xform.translation, [2.5, 0, 0], atol=1e-5)
        player.evaluate(1.0)
        assert np.allclose(xform.translation, [5, 0, 0], atol=1e-5)

    def test_player_loops(self):
        scene = gltf.load_gltf(_animated_translation_glb())
        player = scene.player(0, loop=True)
        xform = scene.node_transforms[0]
        player.evaluate(1.5)     # wraps to t=0.5
        assert np.allclose(xform.translation, [2.5, 0, 0], atol=1e-5)

    def test_cubicspline_endpoints(self):
        scene = gltf.load_gltf(_animated_translation_glb('CUBICSPLINE'))
        player = scene.player(0, loop=False)
        xform = scene.node_transforms[0]
        player.evaluate(1.0)
        assert np.allclose(xform.translation, [5, 0, 0], atol=1e-5)


def _has_network():
    import urllib.request
    try:
        urllib.request.urlopen(gltf.SAMPLE_MODELS_BASE + '/README.md', timeout=6).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_network(), reason="needs network for sample models")
class TestOfficialSampleAnimation:
    """Drive a real Khronos animated sample end-to-end (loader + player)."""

    def _pose(self, node_transforms):
        return {i: (tuple(t.translation), tuple(t.rotation), tuple(t.scale))
                for i, t in node_transforms.items()}

    def test_box_animated_nodes_move(self):
        scene = gltf.load_sample('BoxAnimated')
        assert scene.animations, "BoxAnimated must expose an animation"
        player = scene.player(0, loop=False)
        assert player.duration > 0
        player.evaluate(0.0)
        rest = self._pose(scene.node_transforms)
        player.evaluate(player.duration * 0.5)
        moved = self._pose(scene.node_transforms)
        assert rest != moved, "a node's TRS must change over the animation"

    def test_interpolation_test_loads_all_channels(self):
        scene = gltf.load_sample('InterpolationTest')
        assert scene.animations
        player = scene.player(0, loop=False)
        # sampling anywhere in range must not raise and must be finite
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            player.evaluate(player.duration * frac)
            for t in scene.node_transforms.values():
                assert np.all(np.isfinite(np.asarray(t.rotation)))
                assert np.all(np.isfinite(np.asarray(t.translation)))
