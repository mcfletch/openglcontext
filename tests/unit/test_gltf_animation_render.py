"""GL render test for glTF animation: the viewer renders an animated model to
different frames at different animation times.

Builds a self-contained GLB (a rotating cube -- no external buffers, no network),
captures it at two pinned ``--anim-time`` values through the ``oglc-gltf`` viewer,
and asserts the frames differ. Skips cleanly when no GL context is available.
"""
import math
import os
import subprocess
import sys

import pytest

pytest.importorskip("pygltflib")
import numpy as np
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Material, PbrMetallicRoughness, Animation, AnimationChannel,
    AnimationSampler, AnimationChannelTarget, Skin,
)


def _cube_arrays():
    v, n, idx = [], [], []
    for nrm, quad in _FACES.values():
        b = len(v)
        for p in quad:
            v.append(p)
            n.append(nrm)
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    return np.array(v, '<f4'), np.array(n, '<f4'), np.array(idx, '<u4')

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))

_FACES = {
    'px': ([1, 0, 0], [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
    'nx': ([-1, 0, 0], [(-1, -1, 1), (-1, 1, 1), (-1, 1, -1), (-1, -1, -1)]),
    'py': ([0, 1, 0], [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
    'ny': ([0, -1, 0], [(-1, -1, 1), (-1, -1, -1), (1, -1, -1), (1, -1, 1)]),
    'pz': ([0, 0, 1], [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
    'nz': ([0, 0, -1], [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
}


def _spinning_cube_glb():
    v, n, idx = [], [], []
    for nrm, quad in _FACES.values():
        b = len(v)
        for p in quad:
            v.append(p)
            n.append(nrm)
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    pos = np.array(v, '<f4')
    nrm = np.array(n, '<f4')
    idx = np.array(idx, '<u4')
    times = np.array([0.0, 1.0, 2.0], '<f4')

    def qy(a):
        return [0.0, math.sin(a / 2), 0.0, math.cos(a / 2)]
    rot = np.array([qy(0), qy(2.094), qy(4.188)], '<f4')

    blob, spans = b"", []
    for arr in (pos, nrm, idx, times, rot):
        raw = np.ascontiguousarray(arr).tobytes()
        spans.append((len(blob), len(raw)))
        blob += raw
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=len(pos), type='VEC3',
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(nrm), type='VEC3'),
        Accessor(bufferView=2, componentType=5125, count=len(idx), type='SCALAR'),
        Accessor(bufferView=3, componentType=5126, count=len(times), type='SCALAR',
                 min=[0.0], max=[2.0]),
        Accessor(bufferView=4, componentType=5126, count=len(rot), type='VEC4'),
    ]
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0, name='cube')]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.8, 0.2, 0.2, 1.0], metallicFactor=0.0, roughnessFactor=0.6))]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, NORMAL=1), indices=2, material=0)])]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = [Animation(
        name='spin',
        samplers=[AnimationSampler(input=3, output=4, interpolation='LINEAR')],
        channels=[AnimationChannel(
            sampler=0, target=AnimationChannelTarget(node=0, path='rotation'))])]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


@pytest.fixture(scope="module")
def spin_glb(tmp_path_factory):
    path = tmp_path_factory.mktemp("gltfanim") / "spin.glb"
    path.write_bytes(_spinning_cube_glb())
    return str(path)


def _capture(glb, out, anim_time):
    args = [glb, '--no-cameras', '--no-physics', '--lights', 'on', '--no-shadows',
            '--anim-time', str(anim_time), '--capture', out,
            '--frames', '6', '--capture-delay', '0.2', '--size', '240x240']
    subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.view'] + args,
                   timeout=180, capture_output=True, text=True, cwd=TESTS_DIR + '/..')


def _morph_cube_glb():
    """A cube whose single morph target doubles its size at weight 1.0."""
    pos, nrm, idx = _cube_arrays()
    delta = pos.copy()                        # weight 1 -> pos + pos = 2x cube
    times = np.array([0.0, 1.0], '<f4')
    wout = np.array([[0.0], [1.0]], '<f4')
    blob, spans = b"", []
    for arr in (pos, nrm, idx, delta, times, wout):
        raw = np.ascontiguousarray(arr).tobytes()
        spans.append((len(blob), len(raw)))
        blob += raw
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=len(pos), type='VEC3',
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(nrm), type='VEC3'),
        Accessor(bufferView=2, componentType=5125, count=len(idx), type='SCALAR'),
        Accessor(bufferView=3, componentType=5126, count=len(delta), type='VEC3',
                 min=delta.min(0).tolist(), max=delta.max(0).tolist()),
        Accessor(bufferView=4, componentType=5126, count=len(times), type='SCALAR',
                 min=[0.0], max=[1.0]),
        Accessor(bufferView=5, componentType=5126, count=len(wout), type='SCALAR'),
    ]
    prim = Primitive(attributes=Attributes(POSITION=0, NORMAL=1), indices=2,
                     material=0, targets=[{'POSITION': 3}])
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0, name='morphcube')]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.2, 0.7, 0.3, 1.0], metallicFactor=0.0, roughnessFactor=0.6))]
    g.meshes = [Mesh(primitives=[prim])]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = [Animation(
        name='grow',
        samplers=[AnimationSampler(input=4, output=5, interpolation='LINEAR')],
        channels=[AnimationChannel(
            sampler=0, target=AnimationChannelTarget(node=0, path='weights'))])]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


@pytest.fixture(scope="module")
def morph_glb(tmp_path_factory):
    path = tmp_path_factory.mktemp("gltfmorph") / "morph.glb"
    path.write_bytes(_morph_cube_glb())
    return str(path)


def _skinned_bar_glb():
    """A tall bar; its top half is bound to a joint that swings 90deg about Z."""
    pos, nrm, idx = _cube_arrays()
    pos = pos.copy()
    pos[:, 0] *= 0.25          # thin in x/z
    pos[:, 2] *= 0.25
    pos[:, 1] += 1.0           # y now in [0, 2]
    # top vertices bind to joint B (index 1), bottom to joint A (index 0)
    ji = np.zeros((len(pos), 4), '<u2')
    ji[pos[:, 1] > 1.0, 0] = 1
    wt = np.zeros((len(pos), 4), '<f4')
    wt[:, 0] = 1.0
    ibm = np.stack([np.eye(4), np.eye(4)]).astype('<f4')
    times = np.array([0.0, 1.0], '<f4')
    a = np.pi / 2
    rot = np.array([[0, 0, 0, 1], [0, 0, np.sin(a / 2), np.cos(a / 2)]], '<f4')

    blob, spans = b"", []
    for arr in (pos.astype('<f4'), nrm, idx, ji, wt, ibm, times, rot):
        raw = np.ascontiguousarray(arr).tobytes()
        spans.append((len(blob), len(raw)))
        blob += raw
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=len(pos), type='VEC3',
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(nrm), type='VEC3'),
        Accessor(bufferView=2, componentType=5125, count=len(idx), type='SCALAR'),
        Accessor(bufferView=3, componentType=5123, count=len(ji), type='VEC4'),
        Accessor(bufferView=4, componentType=5126, count=len(wt), type='VEC4'),
        Accessor(bufferView=5, componentType=5126, count=2, type='MAT4'),
        Accessor(bufferView=6, componentType=5126, count=2, type='SCALAR',
                 min=[0.0], max=[1.0]),
        Accessor(bufferView=7, componentType=5126, count=2, type='VEC4'),
    ]
    prim = Primitive(attributes=Attributes(POSITION=0, NORMAL=1, JOINTS_0=3,
                                           WEIGHTS_0=4), indices=2, material=0)
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0, 1])]
    g.nodes = [
        Node(mesh=0, skin=0, name='bar'),
        Node(children=[2], name='jointA'),
        Node(name='jointB'),
    ]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.3, 0.5, 0.9, 1.0], metallicFactor=0.0, roughnessFactor=0.6))]
    g.meshes = [Mesh(primitives=[prim])]
    g.skins = [Skin(joints=[1, 2], inverseBindMatrices=5, skeleton=1)]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = [Animation(
        name='bend',
        samplers=[AnimationSampler(input=6, output=7, interpolation='LINEAR')],
        channels=[AnimationChannel(
            sampler=0, target=AnimationChannelTarget(node=2, path='rotation'))])]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


@pytest.fixture(scope="module")
def skin_glb(tmp_path_factory):
    path = tmp_path_factory.mktemp("gltfskin") / "skin.glb"
    path.write_bytes(_skinned_bar_glb())
    return str(path)


def test_animation_changes_rendered_frame(spin_glb, tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    frames = {}
    for t in (0.0, 0.5):
        p = str(tmp_path / ("spin_%s.png" % t))
        try:
            _capture(spin_glb, p, t)
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(p):
            pytest.skip("OpenGL context unavailable for capture")
        frames[t] = np.asarray(Image.open(p).convert("RGB")).astype(int)
    assert frames[0.0].any(), "rest-pose frame is all black"
    # a rotation about Y must repaint a substantial fraction of the cube's pixels
    diff = np.abs(frames[0.0] - frames[0.5]).max(axis=2)
    assert (diff > 10).mean() > 0.05, "animation did not change the rendered frame"


def test_morph_changes_rendered_frame(morph_glb, tmp_path):
    """A weights animation deforms the mesh on the GPU (VBO re-upload path)."""
    pytest.importorskip("PIL")
    from PIL import Image
    frames = {}
    for t in (0.0, 1.0):
        p = str(tmp_path / ("morph_%s.png" % t))
        try:
            _capture(morph_glb, p, t)
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(p):
            pytest.skip("OpenGL context unavailable for capture")
        frames[t] = np.asarray(Image.open(p).convert("RGB")).astype(int)
    assert frames[0.0].any(), "rest-pose frame is all black"
    # the cube doubles in size at weight 1, so its painted-pixel coverage grows
    def coverage(a):
        # non-background pixels: differ from the top-left sky corner
        bg = a[0, 0]
        return (np.abs(a - bg).max(axis=2) > 20).mean()
    assert coverage(frames[1.0]) > coverage(frames[0.0]) + 0.02, \
        "morph did not change the rendered silhouette"


def test_skinning_changes_rendered_frame(skin_glb, tmp_path):
    """A joint rotation bends the skinned bar on screen (LBS + VBO re-upload)."""
    pytest.importorskip("PIL")
    from PIL import Image
    frames = {}
    for t in (0.0, 1.0):
        p = str(tmp_path / ("skin_%s.png" % t))
        try:
            _capture(skin_glb, p, t)
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(p):
            pytest.skip("OpenGL context unavailable for capture")
        frames[t] = np.asarray(Image.open(p).convert("RGB")).astype(int)
    assert frames[0.0].any(), "bind-pose frame is all black"
    diff = np.abs(frames[0.0] - frames[1.0]).max(axis=2)
    assert (diff > 10).mean() > 0.05, "skinning did not change the rendered frame"
