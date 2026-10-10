"""Basis Universal textures through the optional opengl_basisu transcoder, without GL.

The fixtures in ``tests/unit/basisu_fixtures`` were written by basis_universal's
encoder from flat colours (see the README there). With opengl_basisu
installed, a Basis KTX 2 or ``.basis`` file opens into a
:class:`~OpenGLContext.loaders.basisu.BasisImage` and transcodes to the format
a context's extensions allow; without it, each entry point says which extra to
install.
"""
import pathlib
import struct
import sys

import numpy as np
import pytest

from OpenGLContext.loaders import basisu, textureimages
from OpenGLContext.loaders.textureimages import TextureImageError

FIXTURES = pathlib.Path(__file__).resolve().parent / 'basisu_fixtures'
RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)
CUBE = [(255, 0, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (0, 0, 255), (255, 255, 0)]
DESKTOP = basisu.Capabilities(frozenset({'GL_ARB_texture_compression_bptc'}), (4, 6))

needs_transcoder = pytest.mark.skipif(not basisu.available(),
                                      reason='opengl_basisu is not installed')


def fixture(name):
    return (FIXTURES / name).read_bytes()


def close(found, expected, tolerance=6):
    return np.abs(np.asarray(found, int)[:len(expected)] - np.asarray(expected)).max() <= tolerance


@pytest.fixture
def without_transcoder(monkeypatch):
    """The engine as it is where opengl_basisu is not installed."""
    monkeypatch.setattr(basisu, '_transcoder', lambda: None)


@pytest.mark.parametrize('name', ['etc1s_srgb_mips.ktx2', 'uastc_rgba.ktx2', 'etc1s_rgba.basis'])
def test_a_basis_file_is_recognised(name):
    assert basisu.is_basis(fixture(name))


def test_other_files_are_not_basis():
    plain = b'\xabKTX 20\xbb\r\n\x1a\n' + struct.pack('<9I', 37, 1, 1, 1, 0, 0, 1, 1, 0)
    assert not basisu.is_basis(plain + bytes(40))
    # VK_FORMAT_UNDEFINED with no supercompression and no descriptor to say UASTC
    undefined = b'\xabKTX 20\xbb\r\n\x1a\n' + struct.pack('<9I', 0, 1, 1, 1, 0, 0, 1, 1, 0)
    assert not basisu.is_basis(undefined + bytes(40))
    assert not basisu.is_basis(b'\x89PNG\r\n\x1a\n' + bytes(80))
    assert not basisu.is_basis(b'')


@needs_transcoder
def test_open_image_reports_the_file():
    image = basisu.open_image(fixture('etc1s_srgb_mips.ktx2'))
    assert image.size == (16, 16)
    assert image.levels == 5
    assert image.srgb
    assert not image.has_alpha
    assert image.mode == 'RGB'
    assert image.getbands() == ('R', 'G', 'B')


@needs_transcoder
def test_pixels_top_row_first():
    image = basisu.open_image(fixture('uastc_rgba.ktx2'))
    pixels = image.pixels()
    assert pixels.shape == (16, 16, 4)
    assert tuple(pixels[0, 0]) == RED + (255,)
    assert tuple(pixels[0, 15]) == GREEN + (255,)
    assert tuple(pixels[15, 0]) == BLUE + (255,)
    assert tuple(pixels[15, 15]) == WHITE + (64,)
    assert image.pil().getpixel((15, 15)) == WHITE + (64,)


@needs_transcoder
def test_plan_takes_a_format_the_context_has():
    image = basisu.open_image(fixture('etc1s_srgb_mips.ktx2'))
    target, levels = basisu.plan(image, DESKTOP)
    assert target == 'bc7'
    assert [(level.level, level.width, level.height) for level in levels] == [
        (0, 16, 16), (1, 8, 8), (2, 4, 4), (3, 2, 2), (4, 1, 1)]
    assert all(level.compressed for level in levels)
    # Linear, though the file is sRGB: the shader decodes each map's colour space.
    assert levels[0].internal_format == 0x8E8C
    assert levels[0].data.nbytes == 16 * 16


@needs_transcoder
def test_plan_without_compressed_formats_is_rgba8():
    image = basisu.open_image(fixture('uastc_rgba.ktx2'))
    target, levels = basisu.plan(image, basisu.Capabilities())
    assert target == 'rgba8'
    level = levels[0]
    assert not level.compressed
    assert (level.internal_format, level.gl_format, level.gl_type) == (0x8058, 0x1908, 0x1401)
    assert tuple(level.data[0, 0]) == RED + (255,)


@needs_transcoder
def test_plan_bottom_row_first_is_rgba8_turned_over():
    """An X3D texture puts (0, 0) at the lower left, which a block format cannot be turned to."""
    image = basisu.open_image(fixture('uastc_rgba.ktx2'))
    target, levels = basisu.plan(image, DESKTOP, top_first=False)
    assert target == 'rgba8'
    assert tuple(levels[0].data[0, 0]) == BLUE + (255,)


@needs_transcoder
def test_plan_alpha_skips_formats_without_it():
    image = basisu.open_image(fixture('uastc_rgba.ktx2'))
    target, _levels = basisu.plan(image, basisu.Capabilities(
        frozenset({'GL_EXT_texture_compression_s3tc'}), (3, 3)))
    assert target == 'bc3'


@needs_transcoder
def test_a_basis_cube_map():
    faces = textureimages.read_cube(fixture('etc1s_cube.ktx2'))
    assert len(faces) == 6
    for face, colour in zip(faces, CUBE, strict=True):
        assert face.shape == (8, 8, 3)
        assert close(face.reshape(-1, 3).mean(axis=0), colour)


@needs_transcoder
def test_a_basis_array_is_a_volume():
    volume = textureimages.read_volume(fixture('uastc_array.ktx2'))
    assert volume.shape == (3, 8, 8, 3)
    assert [tuple(volume[index, 0, 0]) for index in range(3)] == [RED, GREEN, BLUE]


@needs_transcoder
def test_a_basis_file_as_one_picture():
    kind, found = textureimages.read_ktx2(fixture('uastc_rgba.ktx2'))
    assert kind == 'image'
    assert tuple(found[0][0, 0]) == RED + (255,)


@needs_transcoder
def test_a_corrupt_basis_file_is_refused():
    data = bytearray(fixture('uastc_rgba.ktx2'))
    data[-40:] = bytes(40)
    with pytest.raises(basisu.BasisTextureError):
        basisu.open_image(bytes(data[:120]))
    with pytest.raises(TextureImageError, match='Basis'):
        textureimages.read_ktx2(bytes(data[:120]))


@needs_transcoder
def test_a_basis_file_that_opens_and_does_not_transcode():
    data = bytearray(fixture('uastc_rgba.ktx2'))
    data[-16:] = bytes(16)
    image = basisu.open_image(bytes(data), url='broken.ktx2')
    assert image.info == {'url': 'broken.ktx2'}
    with pytest.raises(basisu.BasisTextureError, match='does not transcode'):
        image.pixels()
    with pytest.raises(basisu.BasisTextureError, match='does not transcode'):
        basisu.plan(image, DESKTOP)


@needs_transcoder
def test_a_high_dynamic_range_file_is_refused():
    with pytest.raises(basisu.BasisTextureError, match='high dynamic range'):
        basisu.open_image(fixture('uastc_hdr.ktx2'))


def test_the_transcoder_not_importing(monkeypatch):
    monkeypatch.setitem(sys.modules, 'opengl_basisu', None)
    basisu._import_transcoder.cache_clear()  # noqa: SLF001 the import's memo, so this test reaches the import
    try:
        assert basisu._import_transcoder() is None  # noqa: SLF001 as above
    finally:
        basisu._import_transcoder.cache_clear()  # noqa: SLF001 as above


def test_without_the_transcoder(without_transcoder):
    assert not basisu.available()
    assert "OpenGLContext[basisu]" in basisu.missing_reason()
    with pytest.raises(basisu.BasisTextureError, match=r'OpenGLContext\[basisu\]'):
        basisu.open_image(fixture('uastc_rgba.ktx2'))
    with pytest.raises(TextureImageError, match=r'OpenGLContext\[basisu\]'):
        textureimages.read_cube(fixture('etc1s_cube.ktx2'))


# -- glTF KHR_texture_basisu ---------------------------------------------------

def _png(colour):
    import io  # noqa: PLC0415 kept with its use
    from PIL import Image  # noqa: PLC0415 as above
    out = io.BytesIO()
    Image.new('RGB', (8, 8), colour).save(out, format='PNG')
    return out.getvalue()


def _basis_document(ktx2, fallback=None, required=True):
    """A triangle whose base colour is a KHR_texture_basisu texture, with ``fallback`` PNG bytes"""
    pytest.importorskip('pygltflib')
    from OpenGLContext.loaders.gltf.writer import _pack_glb  # noqa: PLC0415 the GLB packer the glTF suites use
    positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
    uvs = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    blob = bytearray(positions.tobytes() + uvs.tobytes())
    views = [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36},
             {'buffer': 0, 'byteOffset': 36, 'byteLength': 24}]
    images = []
    for mime, data in [('image/ktx2', ktx2)] + ([('image/png', fallback)] if fallback else []):
        blob.extend(b'\0' * (-len(blob) % 4))
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(data)})
        images.append({'bufferView': len(views) - 1, 'mimeType': mime})
        blob.extend(data)
    texture = {'extensions': {'KHR_texture_basisu': {'source': 0}}}
    if fallback:
        texture['source'] = 1
    doc = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['KHR_texture_basisu'],
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                    'material': 0}]}],
        'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
        'textures': [texture], 'images': images,
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 3,
             'min': [0, 0, 0], 'max': [1, 1, 0]},
            {'bufferView': 1, 'componentType': 5126, 'type': 'VEC2', 'count': 3}],
        'bufferViews': views, 'buffers': [{'byteLength': len(blob)}],
    }
    if required:
        doc['extensionsRequired'] = ['KHR_texture_basisu']
    return _pack_glb(doc, bytes(blob))


def _base_texture(scene):
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            return node.appearance.material.baseTexture
        stack.extend(getattr(node, 'children', None) or [])
    raise AssertionError('no Shape in the loaded scene')


@pytest.fixture
def fresh_textures():
    from OpenGLContext.loaders.gltf import textures  # noqa: PLC0415 the shared-texture table
    textures.forget_shared_textures()
    yield
    textures.forget_shared_textures()


def _load(document):
    from OpenGLContext.loaders.gltf import load_gltf  # noqa: PLC0415 pygltflib is optional
    return load_gltf(document)


@needs_transcoder
@pytest.mark.usefixtures('fresh_textures')
def test_gltf_basis_texture_is_preferred_to_its_fallback(caplog):
    scene = _load(_basis_document(fixture('uastc_rgba.ktx2'), fallback=_png(BLUE)))
    image = _base_texture(scene).image
    assert isinstance(image, basisu.BasisImage)
    assert image.pil().getpixel((0, 0)) == RED + (255,)
    assert 'KHR_texture_basisu' not in caplog.text


@needs_transcoder
@pytest.mark.usefixtures('fresh_textures')
def test_gltf_basis_texture_that_does_not_transcode_gives_way_to_its_fallback():
    corrupt = fixture('uastc_rgba.ktx2')[:120]
    scene = _load(_basis_document(corrupt, fallback=_png(BLUE)))
    assert _base_texture(scene).image.convert('RGB').getpixel((4, 4)) == BLUE


@pytest.mark.usefixtures('fresh_textures', 'without_transcoder')
def test_gltf_without_the_transcoder_draws_the_fallback(caplog):
    scene = _load(_basis_document(fixture('uastc_rgba.ktx2'), fallback=_png(BLUE)))
    assert _base_texture(scene).image.convert('RGB').getpixel((4, 4)) == BLUE
    reports = [record.getMessage() for record in caplog.records
               if 'KHR_texture_basisu' in record.getMessage()]
    assert len(reports) == 1
    assert "pip install 'OpenGLContext[basisu]'" in reports[0]
    assert '1 are drawn from their fallback image and 0 are not drawn' in reports[0]


@pytest.mark.usefixtures('fresh_textures', 'without_transcoder')
def test_gltf_without_the_transcoder_or_a_fallback(caplog):
    scene = _load(_basis_document(fixture('uastc_rgba.ktx2')))
    assert not _base_texture(scene)
    reports = [record.getMessage() for record in caplog.records
               if 'KHR_texture_basisu' in record.getMessage()]
    assert len(reports) == 1
    assert "OpenGLContext[basisu]" in reports[0]
    assert '0 are drawn from their fallback image and 1 are not drawn' in reports[0]


@needs_transcoder
@pytest.mark.usefixtures('fresh_textures')
def test_gltf_basis_texture_as_pixels():
    """What reads a texture as a picture (a sky, a specular-glossiness map) gets level 0"""
    pytest.importorskip('pygltflib')
    from OpenGLContext.loaders.gltf import loader, textures  # noqa: PLC0415 pygltflib is optional
    from OpenGLContext.loaders.resolver import Resolver  # noqa: PLC0415 as above
    shared = loader.parse_gltf(_basis_document(fixture('uastc_rgba.ktx2')))
    picture = textures.texture_image(shared.gltf, 0, Resolver())
    assert picture.getpixel((15, 15)) == WHITE + (64,)


@needs_transcoder
@pytest.mark.usefixtures('fresh_textures')
def test_gltf_writer_keeps_a_basis_texture_as_ktx2():
    pytest.importorskip('pygltflib')
    from OpenGLContext.loaders.gltf import GLTFWriter, SceneNode  # noqa: PLC0415 pygltflib is optional
    from OpenGLContext.scenegraph.basenodes import Appearance  # noqa: PLC0415 as above
    from OpenGLContext.scenegraph.imagedata import ImageDataTexture  # noqa: PLC0415 as above
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh  # noqa: PLC0415 as above
    from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial  # noqa: PLC0415 as above
    image = basisu.open_image(fixture('uastc_rgba.ktx2'))
    material = PhysicalMaterial(baseTexture=ImageDataTexture(image=image))
    mesh = PBRMesh(positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
                   texcoords=np.array([[0, 0], [1, 0], [0, 1]], np.float32),
                   appearance=Appearance(material=material))
    writer = GLTFWriter()
    writer.add_node(SceneNode(mesh=mesh))
    document = writer.to_glb()
    scene = _load(document)
    found = _base_texture(scene).image
    assert isinstance(found, basisu.BasisImage)
    assert found.data == image.data


# -- X3D texture nodes ---------------------------------------------------------

@needs_transcoder
def test_x3d_image_texture_reads_a_basis_file():
    from OpenGLContext.scenegraph.imagetexture import ImageTexture  # noqa: PLC0415 kept with its use
    node = ImageTexture()
    node.loadFromData(fixture('uastc_rgba.ktx2'), url='file:///albedo.ktx2')
    assert isinstance(node.image, basisu.BasisImage)
    assert node.image.info['url'] == 'file:///albedo.ktx2'
    assert node.hasAlpha()
    assert node.imageSize() == (16, 16)


def test_x3d_image_texture_without_the_transcoder(without_transcoder, caplog):
    from OpenGLContext.scenegraph.imagetexture import ImageTexture  # noqa: PLC0415 kept with its use
    node = ImageTexture()
    assert node.loadFromData(fixture('uastc_rgba.ktx2'), url='albedo.ktx2') is None
    assert "OpenGLContext[basisu]" in caplog.text


@needs_transcoder
def test_roughness_mean_of_a_basis_texture():
    from OpenGLContext.scenegraph.imagedata import ImageDataTexture  # noqa: PLC0415 kept with its use
    node = ImageDataTexture(image=basisu.open_image(fixture('uastc_rgba.ktx2')))
    # Green is 255 in the green and white quadrants, 0 in the others.
    assert node.mean_roughness() == pytest.approx(0.5, abs=0.01)
