"""Per-texture KHR_texture_transform (TextureTransformMultiTest).

The transform is per-texture: a material may transform only its emissive (or
normal / MR / occlusion) map, not its base color. The loader records, per channel,
whether that channel carries a transform (high bits of texCoordMask) so the shader
applies the shared uvTransform only to those channels.
"""
import io

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
PIL = pytest.importorskip("PIL")
from PIL import Image
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Material, PbrMetallicRoughness, TextureInfo, Texture, Image as GImage,
    Sampler,
)

from OpenGLContext.loaders import gltf

# transform-applies bits are the channel bit << 8
T_BASECOLOR = 1 << 8
T_EMISSIVE = 16 << 8


def _png():
    b = io.BytesIO()
    Image.new('RGB', (2, 2), (180, 120, 60)).save(b, format='PNG')
    return b.getvalue()


def _pack(arrays):
    blob, spans = b"", []
    for a in arrays:
        raw = a if isinstance(a, (bytes, bytearray)) else np.ascontiguousarray(a).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    return blob, spans


def _glb(transform_channel):
    """A quad with a base-color + emissive texture; the transform is on whichever
    channel is named (emulating TextureTransformMultiTest's per-channel cells)."""
    pos = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], '<f4')
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], '<f4')
    idx = np.array([0, 1, 2, 0, 2, 3], '<u4')
    png = _png()
    blob, spans = _pack([pos, uv, idx, png])
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=4, type='VEC3',
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=4, type='VEC2'),
        Accessor(bufferView=2, componentType=5125, count=6, type='SCALAR'),
    ]
    xform = {'KHR_texture_transform': {'offset': [0.25, 0.0], 'rotation': 0.0,
                                       'scale': [0.5, 0.5]}}

    def info():
        return TextureInfo(index=0)

    base = info()
    emis = info()
    if transform_channel == 'baseColor':
        base.extensions = dict(xform)
    elif transform_channel == 'emissive':
        emis.extensions = dict(xform)

    mat = Material(pbrMetallicRoughness=PbrMetallicRoughness(baseColorTexture=base),
                   emissiveTexture=emis, emissiveFactor=[1, 1, 1])
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, TEXCOORD_0=1), indices=2, material=0)])]
    g.materials = [mat]
    g.images = [GImage(bufferView=3, mimeType='image/png')]
    g.samplers = [Sampler()]
    g.textures = [Texture(source=0, sampler=0)]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _material(transform_channel):
    scene = gltf.load_gltf(_glb(transform_channel))
    out = []

    def find(n):
        if getattr(n, 'appearance', None) is not None and \
                getattr(n.appearance, 'material', None) is not None:
            out.append(n.appearance.material)
        for c in getattr(n, 'children', []) or []:
            find(c)
    find(scene.group)
    return out[0]


class TestPerTextureTransform:
    def test_transform_on_emissive_only_marks_emissive(self):
        m = _material('emissive')
        assert m.uv_transform is not None
        assert m.texCoordMask & T_EMISSIVE          # emissive transform applies
        assert not (m.texCoordMask & T_BASECOLOR)   # base color is NOT transformed

    def test_transform_on_basecolor_only_marks_basecolor(self):
        m = _material('baseColor')
        assert m.uv_transform is not None
        assert m.texCoordMask & T_BASECOLOR
        assert not (m.texCoordMask & T_EMISSIVE)

    def test_no_transform_marks_nothing(self):
        m = _material(None)
        assert m.uv_transform is None
        assert not (m.texCoordMask & (T_BASECOLOR | T_EMISSIVE))


class TestUVTransformMatrix:
    """uv_transform_matrix builds the mat3 the shader applies as uvTransform*(uv,1)."""

    def _apply(self, M, u, v):
        M = np.asarray(M, float)
        return (M[0][0] * u + M[0][1] * v + M[0][2],
                M[1][0] * u + M[1][1] * v + M[1][2])

    def test_pure_offset_translates(self):
        from OpenGLContext.scenegraph.pbrmaterial import uv_transform_matrix
        M = uv_transform_matrix(offset=(0.5, 0.25))
        assert self._apply(M, 0.0, 0.0) == (0.5, 0.25)

    def test_scale_multiplies(self):
        from OpenGLContext.scenegraph.pbrmaterial import uv_transform_matrix
        M = uv_transform_matrix(scale=(1.5, 2.0))
        assert self._apply(M, 1.0, 1.0) == (1.5, 2.0)

    def test_rotation_sense_matches_gltf_conformance(self):
        # TextureTransformTest's Rotation cell lands on "Correct" only when the U
        # axis rotates toward -V for a positive angle (our texcoords are authored
        # V-down, so the spec matrix's sense is inverted). A 90-degree rotation must
        # send (u=1, v=0) to (0, -1); the un-negated spec matrix would give (0, +1)
        # and the cell renders "Error".
        import math
        from OpenGLContext.scenegraph.pbrmaterial import uv_transform_matrix
        M = uv_transform_matrix(rotation=math.pi / 2)
        u2, v2 = self._apply(M, 1.0, 0.0)
        assert abs(u2 - 0.0) < 1e-6 and abs(v2 - (-1.0)) < 1e-6


# --- GL render: a base-color transform shifts the sampled texture -------------
import os
import subprocess
import sys

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))


def _split_png():
    a = np.zeros((4, 4, 3), 'u1')
    a[:, :2] = (220, 30, 30)    # left half red
    a[:, 2:] = (30, 200, 30)    # right half green
    b = io.BytesIO()
    Image.fromarray(a, 'RGB').save(b, format='PNG')
    return b.getvalue()


def _unlit_quad_glb(offset):
    pos = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], '<f4')
    uv = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], '<f4')
    idx = np.array([0, 1, 2, 0, 2, 3], '<u4')
    png = _split_png()
    blob, spans = _pack([pos, uv, idx, png])
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=4, type='VEC3',
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=4, type='VEC2'),
        Accessor(bufferView=2, componentType=5125, count=6, type='SCALAR'),
    ]
    base = TextureInfo(index=0)
    if offset:
        base.extensions = {'KHR_texture_transform': {'offset': [offset, 0.0],
                                                     'scale': [1.0, 1.0]}}
    mat = Material(pbrMetallicRoughness=PbrMetallicRoughness(baseColorTexture=base),
                   doubleSided=True)
    mat.extensions = {'KHR_materials_unlit': {}}
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, TEXCOORD_0=1), indices=2, material=0)])]
    g.materials = [mat]
    g.images = [GImage(bufferView=3, mimeType='image/png')]
    g.samplers = [Sampler()]
    g.textures = [Texture(source=0, sampler=0)]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _capture(glb, out):
    args = [glb, '--no-cameras', '--no-physics', '--no-shadows', '--no-rotate',
            '--lights', 'on', '--background', '0,0,0', '--capture', out,
            '--frames', '6', '--capture-delay', '0.2', '--size', '200x200']
    subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.view'] + args,
                   timeout=180, capture_output=True, text=True, cwd=TESTS_DIR + '/..')


def _green_frac(arr):
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    return float(((g > 90) & (g > r + 30)).mean())


def test_basecolor_transform_shifts_texture(tmp_path):
    """Offsetting the base-color UVs by +0.5 slides the split texture, changing how
    much green shows -- proof the per-texture transform reaches the GPU."""
    fracs = {}
    for off in (0.0, 0.5):
        glb = tmp_path / ("t%s.glb" % off)
        glb.write_bytes(_unlit_quad_glb(off))
        out = str(tmp_path / ("t%s.png" % off))
        try:
            _capture(str(glb), out)
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(out):
            pytest.skip("OpenGL context unavailable for capture")
        fracs[off] = _green_frac(np.asarray(Image.open(out).convert("RGB")))
    assert abs(fracs[0.0] - fracs[0.5]) > 0.05, (
        "the base-color KHR_texture_transform did not change the render "
        "(green off=%.3f on=%.3f)" % (fracs[0.0], fracs[0.5]))
