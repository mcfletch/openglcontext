"""GL render test for the optional HDR bloom pass (OPENGLCONTEXT_BLOOM).

Emissive cubes of increasing KHR_materials_emissive_strength: with bloom off they
clamp flat; with bloom on the bright emissive blooms into a glow that bleeds past
the cube edges (and a stronger cube glows more). The pass is gated, so bloom-off
must render exactly as before.
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


def _cube():
    v, n, idx = [], [], []
    for nrm, quad in _FACES.values():
        b = len(v)
        for p in quad:
            v.append(p)
            n.append(nrm)
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    return np.array(v, '<f4') * 0.6, np.array(n, '<f4'), np.array(idx, '<u4')


def _emissive_glb():
    pos, nrm, idx = _cube()
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
    strengths = [1, 4, 16, 64]
    g.nodes, g.meshes, g.materials = [], [], []
    for i, s in enumerate(strengths):
        m = Material(pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorFactor=[0.02, 0.02, 0.02, 1], metallicFactor=0, roughnessFactor=1),
            emissiveFactor=[0.1, 0.5, 0.9])
        m.extensions = {'KHR_materials_emissive_strength': {'emissiveStrength': s}}
        g.materials.append(m)
        g.meshes.append(Mesh(primitives=[Primitive(
            attributes=Attributes(POSITION=0, NORMAL=1), indices=2, material=i)]))
        g.nodes.append(Node(mesh=i, translation=[i * 2.4 - 3.6, 0, 0]))
    g.extensionsUsed = ['KHR_materials_emissive_strength']
    g.scenes = [Scene(nodes=list(range(len(strengths))))]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _capture(glb, out, bloom):
    env = dict(os.environ, OPENGLCONTEXT_BLOOM=('1' if bloom else '0'))
    args = [glb, '--no-cameras', '--no-physics', '--no-shadows', '--no-rotate',
            '--lights', 'on', '--background', '0,0,0', '--capture', out,
            '--frames', '6', '--capture-delay', '0.3', '--size', '360x140']
    subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.gltf_view'] + args,
                   timeout=180, capture_output=True, text=True,
                   cwd=TESTS_DIR + '/..', env=env)


def _glow(arr):
    # fraction of the frame that is a soft mid-bright glow (bloom bleed), i.e. lit but
    # not the solid cube core -- rises sharply when bloom spreads emissive outward.
    lum = arr.max(axis=2)
    return float(((lum > 25) & (lum < 210)).mean())


def test_bloom_adds_glow(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    glb = tmp_path / "emis.glb"
    glb.write_bytes(_emissive_glb())
    frames = {}
    for bloom in (False, True):
        out = str(tmp_path / ("b%d.png" % bloom))
        try:
            _capture(str(glb), out, bloom)
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(out):
            pytest.skip("OpenGL context unavailable for capture")
        frames[bloom] = np.asarray(Image.open(out).convert("RGB")).astype(int)
    assert frames[False].any(), "bloom-off frame is blank"
    assert frames[True].any(), "bloom-on frame is blank"
    g_off, g_on = _glow(frames[False]), _glow(frames[True])
    assert g_on > g_off + 0.02, ("bloom should spread emissive into a glow "
                                 "(glow off=%.3f on=%.3f)" % (g_off, g_on))
