"""A KHR_texture_basisu texture as it is drawn (GL, PBR core).

The texture is ``etc1s_srgb_mips.ktx2``: 16x16 quadrants, red and green over
blue and white, five mip levels. It is drawn unlit on a quad that fills the
middle of the view, once in each format the transcoder writes, by limiting
what the context is said to offer; each draw shows the four quadrants where
glTF puts them, the image's top row at the top.
"""
import pathlib

import numpy as np
import pytest

pytest.importorskip("glfw")
pytest.importorskip("pygltflib")

from OpenGLContext import texture
from OpenGLContext.loaders import basisu
from OpenGLContext.loaders.gltf import load_gltf
from OpenGLContext.loaders.gltf import textures as gtextures
from OpenGLContext.loaders.gltf.writer import _pack_glb
from OpenGLContext.scenegraph import basenodes
from tests.unit.glrender import base_env, frames_of

pytestmark = pytest.mark.skipif(not basisu.available(), reason='opengl_basisu is not installed')

FIXTURES = pathlib.Path(__file__).resolve().parent / 'basisu_fixtures'
SIZE = (160, 160)
QUADRANTS = {'top left': (255, 0, 0), 'top right': (0, 255, 0),
             'bottom left': (0, 0, 255), 'bottom right': (255, 255, 255)}

POSITIONS = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], np.float32)
# glTF puts texture coordinate (0, 0) at the image's upper left.
UVS = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], np.float32)
INDICES = np.array([0, 1, 2, 0, 2, 3], np.uint16)


def basis_quad(ktx2: bytes) -> bytes:
    """A GLB of one unlit quad whose base colour is ``ktx2``, by KHR_texture_basisu alone"""
    blob = bytearray(POSITIONS.tobytes() + UVS.tobytes() + INDICES.tobytes())
    views = [{'buffer': 0, 'byteOffset': 0, 'byteLength': 48},
             {'buffer': 0, 'byteOffset': 48, 'byteLength': 32},
             {'buffer': 0, 'byteOffset': 80, 'byteLength': 12}]
    blob.extend(b'\0' * (-len(blob) % 4))
    views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(ktx2)})
    blob.extend(ktx2)
    doc = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['KHR_materials_unlit', 'KHR_texture_basisu'],
        'extensionsRequired': ['KHR_texture_basisu'],
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                    'indices': 2, 'material': 0}]}],
        'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}},
                       'extensions': {'KHR_materials_unlit': {}}}],
        'textures': [{'extensions': {'KHR_texture_basisu': {'source': 0}}}],
        'images': [{'bufferView': 3, 'mimeType': 'image/ktx2'}],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 4,
             'min': [-1, -1, 0], 'max': [1, 1, 0]},
            {'bufferView': 1, 'componentType': 5126, 'type': 'VEC2', 'count': 4},
            {'bufferView': 2, 'componentType': 5123, 'type': 'SCALAR', 'count': 6}],
        'bufferViews': views, 'buffers': [{'byteLength': len(blob)}],
    }
    return _pack_glb(doc, bytes(blob))


@pytest.fixture
def env(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
    gtextures.forget_shared_textures()
    yield monkeypatch
    gtextures.forget_shared_textures()


def uploads(monkeypatch):
    """The target format and GL internal format of each Basis texture uploaded"""
    from OpenGL import GL  # noqa: PLC0415 kept with the one query that needs it
    made = []
    real = texture.BasisTexture.store_basis

    def recording(self, image):
        real(self, image)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        made.append((self.target_format, int(GL.glGetTexLevelParameteriv(
            GL.GL_TEXTURE_2D, 0, GL.GL_TEXTURE_INTERNAL_FORMAT))))
    monkeypatch.setattr(texture.BasisTexture, 'store_basis', recording)
    return made


def offering(monkeypatch, extensions, version=(3, 3)):
    """The context said to offer only ``extensions`` at ``version``"""
    monkeypatch.setattr(texture, 'compressed_capabilities',
                        lambda: basisu.Capabilities(frozenset(extensions), version))


def quadrants(frame):
    height, width = frame.shape[:2]
    middle_y, middle_x, step = height // 2, width // 2, width // 8
    return {'top left': frame[middle_y - step, middle_x - step],
            'top right': frame[middle_y - step, middle_x + step],
            'bottom left': frame[middle_y + step, middle_x - step],
            'bottom right': frame[middle_y + step, middle_x + step]}


def drawn(render_scene, scene):
    children = [basenodes.Viewpoint(position=(0.0, 0.0, 2.6)),
                basenodes.NavigationInfo(headlight=False), scene.group]
    return frames_of(render_scene, children, frames=3, size=SIZE)[-1].astype(int)


def base_texture(scene):
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            return node.appearance.material.baseTexture
        stack.extend(getattr(node, 'children', None) or [])
    raise AssertionError('no Shape in the loaded scene')


@pytest.mark.parametrize('extensions, target, internal_format', [
    ({'GL_ARB_texture_compression_bptc'}, 'bc7', 0x8E8C),
    ({'GL_EXT_texture_compression_s3tc'}, 'bc1', 0x83F0),
    ({'GL_ARB_ES3_compatibility'}, 'etc1', 0x9274),
    ({'GL_KHR_texture_compression_astc_ldr'}, 'astc_4x4', 0x93B0),
    (set(), 'rgba8', 0x8058),
])
@pytest.mark.usefixtures('env')
def test_a_basis_texture_draws_its_quadrants(render_scene, monkeypatch, extensions, target,
                                             internal_format):
    offering(monkeypatch, extensions)
    made = uploads(monkeypatch)
    scene = load_gltf(basis_quad((FIXTURES / 'etc1s_srgb_mips.ktx2').read_bytes()))
    found = quadrants(drawn(render_scene, scene))
    for name, colour in QUADRANTS.items():
        assert np.abs(found[name] - colour).max() <= 12, (name, found[name], colour)
    assert made == [(target, internal_format)]


@pytest.mark.usefixtures('env')
def test_the_context_is_asked_what_it_offers(render_scene, monkeypatch):
    made = uploads(monkeypatch)
    scene = load_gltf(basis_quad((FIXTURES / 'etc1s_srgb_mips.ktx2').read_bytes()))
    found = quadrants(drawn(render_scene, scene))
    for name, colour in QUADRANTS.items():
        assert np.abs(found[name] - colour).max() <= 12, (name, found[name], colour)
    # What the driver reports decides it: every desktop GL 3.3 driver has S3TC or BPTC.
    assert [target for target, _format in made] in (['bc7'], ['bc1'], ['astc_4x4'])


def x3d_quad(texture_node):
    """A unit quad facing the viewer, texture coordinate (0, 0) at its lower left, as X3D's"""
    return basenodes.Shape(
        appearance=basenodes.Appearance(
            material=basenodes.UnlitMaterial(emissiveColor=(1, 1, 1),
                                             emissiveTexture=texture_node)),
        geometry=basenodes.IndexedFaceSet(
            coord=basenodes.Coordinate(point=POSITIONS.tolist()),
            texCoord=basenodes.TextureCoordinate(point=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            coordIndex=[0, 1, 2, 3, -1], texCoordIndex=[0, 1, 2, 3, -1], solid=False))


@pytest.mark.usefixtures('env')
def test_an_x3d_image_texture_of_a_basis_file(render_scene, monkeypatch):
    """X3D's (0, 0) is the image's lower left: the texture is RGBA8 turned over"""
    from OpenGLContext.scenegraph.imagetexture import ImageTexture  # noqa: PLC0415 kept with its use
    made = uploads(monkeypatch)
    node = ImageTexture()
    node.loadFromData((FIXTURES / 'etc1s_srgb_mips.ktx2').read_bytes(), url='quadrants.ktx2')
    children = [basenodes.Viewpoint(position=(0.0, 0.0, 2.6)),
                basenodes.NavigationInfo(headlight=False), x3d_quad(node)]
    frame = frames_of(render_scene, children, frames=3, size=SIZE)[-1].astype(int)
    found = quadrants(frame)
    for name, colour in QUADRANTS.items():
        assert np.abs(found[name] - colour).max() <= 12, (name, found[name], colour)
    assert [target for target, _format in made] == ['rgba8']


def test_one_level_is_sampled_without_mipmaps(gl_context):
    """A block format cannot have its mipmaps generated; one level is sampled alone"""
    from OpenGL import GL  # noqa: PLC0415 kept with the queries that need it

    from OpenGLContext.scenegraph.sampler import apply_sampler  # noqa: PLC0415 as above
    image = basisu.open_image((FIXTURES / 'uastc_rgba.ktx2').read_bytes())
    held = texture.BasisTexture(image, topFirst=True)
    assert held.mip_levels == 1
    apply_sampler(held, {'minification': 'AVG_PIXEL_AVG_MIPMAP', 'magnification': 'AVG_PIXEL'})
    assert GL.glGetTexParameteriv(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER) == GL.GL_LINEAR
    assert GL.glGetError() == GL.GL_NO_ERROR


def test_a_mip_chain_is_kept(gl_context):
    from OpenGL import GL  # noqa: PLC0415 kept with the queries that need it

    from OpenGLContext.scenegraph.sampler import apply_sampler  # noqa: PLC0415 as above
    image = basisu.open_image((FIXTURES / 'etc1s_srgb_mips.ktx2').read_bytes())
    held = texture.BasisTexture(image, topFirst=True)
    assert held.mip_levels == 5
    apply_sampler(held, {'minification': 'AVG_PIXEL_AVG_MIPMAP', 'magnification': 'AVG_PIXEL'})
    assert GL.glGetTexParameteriv(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER) == \
        GL.GL_LINEAR_MIPMAP_LINEAR
    assert GL.glGetTexParameteriv(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAX_LEVEL) == 4
    assert GL.glGetError() == GL.GL_NO_ERROR
