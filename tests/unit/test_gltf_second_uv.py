"""Second UV set (TEXCOORD_1) + per-texture texCoord selection.

Covers MultiUVTest / Beautiful Game (a texture bound to UV set 1 must sample UV1,
not UV0). Loader-level (no GL): the mesh carries a second UV array and the material
records, per texture channel, which UV set it uses (a bitmask packed into the UBO).
"""
import io
import struct

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
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

# texCoord-mask bit per channel (must match the loader + shader).
BIT_BASECOLOR = 1
BIT_METALLICROUGHNESS = 2
BIT_NORMAL = 4
BIT_OCCLUSION = 8
BIT_EMISSIVE = 16


def _png_bytes(color=(200, 40, 40)):
    img = Image.new('RGB', (2, 2), color)
    b = io.BytesIO()
    img.save(b, format='PNG')
    return b.getvalue()


def _pack(arrays):
    blob, spans = b"", []
    for a in arrays:
        raw = a if isinstance(a, (bytes, bytearray)) else np.ascontiguousarray(a).tobytes()
        # 4-byte align each span (bufferView offsets for float accessors)
        pad = (-len(blob)) % 4
        blob += b"\x00" * pad
        spans.append((len(blob), len(raw)))
        blob += raw
    return blob, spans


def _multi_uv_glb(base_tex_coord=1):
    pos = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype='<f4')
    uv0 = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype='<f4')
    uv1 = np.array([[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]], dtype='<f4')  # different
    idx = np.array([0, 1, 2, 0, 2, 3], dtype='<u4')
    png = _png_bytes()

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
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorTexture=TextureInfo(index=0, texCoord=base_tex_coord)))]
    g.images = [GImage(bufferView=4, mimeType='image/png')]
    g.samplers = [Sampler()]
    g.textures = [Texture(source=0, sampler=0)]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _find_shape(node):
    for child in getattr(node, 'children', []) or []:
        if getattr(child, 'geometry', None) is not None:
            return child
        found = _find_shape(child)
        if found is not None:
            return found
    return None


class TestSecondUVSet:
    def test_mesh_carries_second_uv(self):
        scene = gltf.load_gltf(_multi_uv_glb())
        mesh = _find_shape(scene.group).geometry
        assert mesh.texcoords1 is not None
        assert mesh.texcoords1.shape == (4, 2)
        # UV1 differs from UV0
        assert not np.allclose(mesh.texcoords, mesh.texcoords1)

    def test_material_records_texcoord1_for_basecolor(self):
        scene = gltf.load_gltf(_multi_uv_glb(base_tex_coord=1))
        mat = _find_shape(scene.group).appearance.material
        assert isinstance(mat, PBRMaterial)
        assert mat.texCoordMask & BIT_BASECOLOR   # base color uses UV set 1

    def test_texcoord0_leaves_mask_clear(self):
        scene = gltf.load_gltf(_multi_uv_glb(base_tex_coord=0))
        mat = _find_shape(scene.group).appearance.material
        assert not (mat.texCoordMask & BIT_BASECOLOR)   # base color uses UV set 0

    def test_no_second_uv_when_absent(self):
        # a plain single-UV model must not sprout a texcoords1 array
        from tests.unit.test_gltf_loader import _triangle_glb
        scene = gltf.load_gltf(_triangle_glb())
        mesh = _find_shape(scene.group).geometry
        assert getattr(mesh, 'texcoords1', None) is None


class TestMaterialBlockPacking:
    def test_texcoordmask_packed_into_ubo(self):
        from OpenGLContext.passes.pbrpass import pack_material_block, MATERIAL_BLOCK_WORDS
        mat = PBRMaterial(baseColor=(1, 1, 1))
        mat.texCoordMask = BIT_NORMAL | BIT_OCCLUSION
        buf = pack_material_block(mat)
        assert len(buf) == MATERIAL_BLOCK_WORDS      # layout size unchanged
        iv = buf.view(np.int32)
        assert iv[29] == (BIT_NORMAL | BIT_OCCLUSION)
