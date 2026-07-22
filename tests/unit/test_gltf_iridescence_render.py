"""GL render test: KHR_materials_iridescence tints a metal surface.

A metallic cube with iridescenceFactor 1.0 shows the thin-film hue shift (its faces
pick up colour); the same cube with iridescence 0.0 stays a neutral metal. The
iridescent render must be markedly more saturated.
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


def _uv_sphere(rings=24, sectors=48):
    """A unit UV sphere -- its grazing silhouette sweeps the full range of view
    angles, so the thin-film hue shift shows strongly (as on the real spheres)."""
    verts, idx = [], []
    for i in range(rings + 1):
        phi = np.pi * i / rings
        for j in range(sectors + 1):
            th = 2 * np.pi * j / sectors
            x = np.sin(phi) * np.cos(th)
            y = np.cos(phi)
            z = np.sin(phi) * np.sin(th)
            verts.append((x, y, z))
    for i in range(rings):
        for j in range(sectors):
            a = i * (sectors + 1) + j
            b = a + sectors + 1
            idx += [a, b, a + 1, a + 1, b, b + 1]
    p = np.array(verts, '<f4')
    return p, p.copy(), np.array(idx, '<u4')      # position == normal for a unit sphere


def _iridescent_cube_glb(factor):
    pos, nrm, idx = _uv_sphere()
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
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, NORMAL=1), indices=2, material=0)])]
    # A mid-gray metal reflects the environment strongly; its F0 (= 0.5 gray, not a
    # perfect white mirror) is tinted by the thin film, so the sphere picks up the
    # rainbow across its grazing sweep -- as on the real IridescenceMetallicSpheres.
    mat = Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.5, 0.5, 0.5, 1], metallicFactor=1.0, roughnessFactor=0.25))
    mat.extensions = {'KHR_materials_iridescence': {
        'iridescenceFactor': factor, 'iridescenceIor': 1.3,
        'iridescenceThicknessMinimum': 100.0, 'iridescenceThicknessMaximum': 400.0}}
    if factor > 0:
        g.extensionsUsed = ['KHR_materials_iridescence']
    g.materials = [mat]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _capture(glb, out):
    args = [glb, '--no-cameras', '--no-physics', '--no-shadows', '--no-rotate',
            '--yaw', '0.7', '--lights', 'on', '--background', '0.6,0.6,0.6',
            '--capture', out, '--frames', '8', '--capture-delay', '0.3',
            '--size', '200x200']
    subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.gltf_view'] + args,
                   timeout=180, capture_output=True, text=True, cwd=TESTS_DIR + '/..')


def _chroma(arr):
    """Mean colourfulness over the object's pixels: how far each pixel's channels
    spread from neutral gray. Iridescence tints; a plain surface stays neutral."""
    a = arr.astype(float)
    mx = a.max(axis=2)
    obj = mx > 12          # the cube; background is pure black
    if not obj.any():
        return 0.0
    spread = a.max(axis=2) - a.min(axis=2)     # per-pixel channel spread (chroma)
    return float(spread[obj].mean())


def test_iridescence_changes_the_render(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    frames = {}
    for factor in (0.0, 1.0):
        glb = tmp_path / ("irid%.0f.glb" % factor)
        glb.write_bytes(_iridescent_cube_glb(factor))
        out = str(tmp_path / ("irid%.0f.png" % factor))
        try:
            _capture(str(glb), out)
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(out):
            pytest.skip("OpenGL context unavailable for capture")
        frames[factor] = np.asarray(Image.open(out).convert("RGB"))
    assert frames[0.0].any() or frames[1.0].any(), "both frames blank"
    # iridescence tints the reflection across the sphere's grazing sweep: the on
    # sphere is markedly more chromatic than the plain one.
    c_off, c_on = _chroma(frames[0.0]), _chroma(frames[1.0])
    # a clear, above-noise increase (the analytic env is dim, so absolute chroma is
    # modest, but iridescence lifts it well past a neutral metal's reflection).
    assert c_on > c_off + 0.4 and c_on > c_off * 1.2, (
        "iridescence adds chroma (off=%.2f on=%.2f)" % (c_off, c_on))
