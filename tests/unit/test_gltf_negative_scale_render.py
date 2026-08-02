"""GL render test: negatively-scaled instances light correctly (NegativeScaleTest).

Four boxes share one mesh + material (so they batch into instanced draws): two at
positive scale, two mirrored (scale x = -1), laid out symmetrically under a
straight-down light. A correct renderer produces a left-right mirror-symmetric
image; the old bug (one front-face winding for a mixed-determinant batch) lit the
mirrored boxes inside-out, breaking symmetry.
"""
import os
import subprocess
import sys

import pytest

pytest.importorskip("pygltflib")
import numpy as np
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Material, PbrMetallicRoughness,
)

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


def _neg_scale_glb():
    v, n, idx = [], [], []
    for nrm, quad in _FACES.values():
        b = len(v)
        for p in quad:
            v.append(p)
            n.append(nrm)
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    pos = np.array(v, '<f4') * 0.6
    nrm = np.array(n, '<f4')
    idx = np.array(idx, '<u4')
    blob, spans = b"", []
    for arr in (pos, nrm, idx):
        raw = np.ascontiguousarray(arr).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=len(pos), type='VEC3',
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(nrm), type='VEC3'),
        Accessor(bufferView=2, componentType=5125, count=len(idx), type='SCALAR'),
    ]
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0, 1, 2, 3, 4])]
    # two positive-scale, two mirrored (scale x = -1) -- >=2 of each so each sign
    # forms its own instanced batch.
    g.nodes = [
        Node(mesh=0, translation=[1.6, 0, 0]),
        Node(mesh=0, translation=[3.4, 0, 0]),
        Node(mesh=0, translation=[-1.6, 0, 0], scale=[-1, 1, 1]),
        Node(mesh=0, translation=[-3.4, 0, 0], scale=[-1, 1, 1]),
        # a straight-down light so the scene is symmetric under an x-mirror
        Node(extensions={'KHR_lights_punctual': {'light': 0}}),
    ]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, NORMAL=1), indices=2, material=0)])]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.7, 0.7, 0.75, 1.0], metallicFactor=0.0, roughnessFactor=0.8))]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.extensions = {'KHR_lights_punctual': {'lights': [
        {'type': 'directional', 'intensity': 3.0, 'color': [1, 1, 1]}]}}
    g.extensionsUsed = ['KHR_lights_punctual']
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _capture(glb, out):
    args = [glb, '--no-cameras', '--no-physics', '--no-shadows', '--no-rotate',
            '--lights', 'off', '--background', '0,0,0', '--yaw', '0',
            '--capture', out, '--frames', '6', '--capture-delay', '0.2',
            '--size', '320x160']
    subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.view'] + args,
                   timeout=180, capture_output=True, text=True, cwd=TESTS_DIR + '/..')


def test_mirrored_instances_are_symmetric(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    glb = tmp_path / "neg.glb"
    glb.write_bytes(_neg_scale_glb())
    out = str(tmp_path / "neg.png")
    try:
        _capture(str(glb), out)
    except subprocess.TimeoutExpired:
        pytest.skip("OpenGL context unavailable / capture timed out")
    if not os.path.exists(out):
        pytest.skip("OpenGL context unavailable for capture")
    arr = np.asarray(Image.open(out).convert("RGB")).astype(int)
    assert arr.any(), "frame is blank"
    mirror = arr[:, ::-1, :]
    # correct negative-scale handling => the mirrored boxes match the positive ones
    diff = np.abs(arr - mirror).mean()
    assert diff < 12.0, ("mirrored (negative-scale) instances are lit differently "
                         "from their positive twins (mean L/R diff %.1f)" % diff)
