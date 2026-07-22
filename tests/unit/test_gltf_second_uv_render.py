"""GL render test: a texture bound to TEXCOORD_1 samples the second UV set.

An unlit quad carries UV0 spanning the whole texture and UV1 spanning only its left
(red) half. With the base-color texture on texCoord 0 the quad shows red|green; on
texCoord 1 it shows (almost) all red. Rendering both and comparing the green
coverage proves the shader picks the right UV set per texture.
"""
import io
import os
import subprocess
import sys

import pytest

pytest.importorskip("pygltflib")
PIL = pytest.importorskip("PIL")
import numpy as np
from PIL import Image
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Material, PbrMetallicRoughness, TextureInfo, Texture, Image as GImage,
    Sampler,
)

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))


def _split_png():
    # 4x4: left two columns red, right two columns green
    a = np.zeros((4, 4, 3), 'u1')
    a[:, :2] = (220, 30, 30)
    a[:, 2:] = (30, 200, 30)
    b = io.BytesIO()
    Image.fromarray(a, 'RGB').save(b, format='PNG')
    return b.getvalue()


def _pack(arrays):
    blob, spans = b"", []
    for a in arrays:
        raw = a if isinstance(a, (bytes, bytearray)) else np.ascontiguousarray(a).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    return blob, spans


def _uv_glb(base_tex_coord):
    pos = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], dtype='<f4')
    uv0 = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], dtype='<f4')          # full texture
    uv1 = np.array([[0, 1], [0.5, 1], [0.5, 0], [0, 0]], dtype='<f4')      # left half only
    idx = np.array([0, 1, 2, 0, 2, 3], dtype='<u4')
    png = _split_png()
    blob, spans = _pack([pos, uv0, uv1, idx, png])
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=4, type='VEC3',
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=4, type='VEC2'),
        Accessor(bufferView=2, componentType=5126, count=4, type='VEC2'),
        Accessor(bufferView=3, componentType=5125, count=6, type='SCALAR'),
    ]
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, TEXCOORD_0=1, TEXCOORD_1=2),
        indices=3, material=0)])]
    mat = Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorTexture=TextureInfo(index=0, texCoord=base_tex_coord)),
        doubleSided=True)
    mat.extensions = {'KHR_materials_unlit': {}}   # emit base color directly
    g.materials = [mat]
    g.images = [GImage(bufferView=4, mimeType='image/png')]
    g.samplers = [Sampler()]
    g.textures = [Texture(source=0, sampler=0)]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _capture(glb_path, out):
    args = [glb_path, '--no-cameras', '--no-physics', '--no-shadows', '--no-rotate',
            '--lights', 'on', '--background', '0,0,0', '--capture', out,
            '--frames', '6', '--capture-delay', '0.2', '--size', '200x200']
    subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.gltf_view'] + args,
                   timeout=180, capture_output=True, text=True, cwd=TESTS_DIR + '/..')


def _green_fraction(arr):
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    return float(((g > 90) & (g > r + 30)).mean())


def test_texcoord1_samples_second_uv(tmp_path):
    frames = {}
    for tc in (0, 1):
        glb = tmp_path / ("uv%d.glb" % tc)
        glb.write_bytes(_uv_glb(tc))
        out = str(tmp_path / ("uv%d.png" % tc))
        try:
            _capture(str(glb), out)
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(out):
            pytest.skip("OpenGL context unavailable for capture")
        frames[tc] = np.asarray(Image.open(out).convert("RGB"))
    assert frames[0].any(), "texCoord0 frame is blank"
    g0, g1 = _green_fraction(frames[0]), _green_fraction(frames[1])
    # texCoord0 shows the green right half; texCoord1 (left-half UVs) shows ~none.
    assert g0 > 0.05, "texCoord0 quad should show the texture's green half (got %.3f)" % g0
    assert g0 > g1 + 0.05, (
        "texCoord1 must sample UV set 1 (mostly red): green0=%.3f green1=%.3f" % (g0, g1))
