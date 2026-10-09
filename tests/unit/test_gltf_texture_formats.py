"""Texture images in formats an extension names: EXT_texture_avif, EXT_texture_webp.

Each extension names an image the texture prefers to its core ``source``,
which is the fallback for a reader without the format. The images are made
with Pillow in the test.
"""
import io

import numpy as np
import pytest

pytest.importorskip("pygltflib")
Image = pytest.importorskip("PIL.Image")
features = pytest.importorskip("PIL.features")

from OpenGLContext.loaders.gltf import EncodedImage, GLTFWriter, SceneNode, load_gltf
from OpenGLContext.loaders.gltf import textures as gtextures
from OpenGLContext.loaders.gltf.writer import _pack_glb
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.basenodes import Appearance

RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)
TRIANGLE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
UV = np.array([[0, 0], [1, 0], [0, 1]], np.float32)


def _encoded(colour, format):
    out = io.BytesIO()
    Image.new('RGB', (8, 8), colour).save(out, format=format)
    return out.getvalue()


def _document(images, texture):
    """A triangle whose base colour is texture 0, given as ``texture``; each of
    ``images`` is (mime type, bytes) in a buffer view."""
    blob = bytearray(TRIANGLE.tobytes() + UV.tobytes())
    views = [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36},
             {'buffer': 0, 'byteOffset': 36, 'byteLength': 24}]
    entries = []
    for mime, data in images:
        blob.extend(b'\0' * (-len(blob) % 4))
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(data)})
        entries.append({'bufferView': len(views) - 1, 'mimeType': mime})
        blob.extend(data)
    used = sorted({name for name in (texture.get('extensions') or {})})
    doc = {
        'asset': {'version': '2.0'},
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                    'material': 0}]}],
        'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
        'textures': [texture], 'images': entries,
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 3,
             'min': [0, 0, 0], 'max': [1, 1, 0]},
            {'bufferView': 1, 'componentType': 5126, 'type': 'VEC2', 'count': 3}],
        'bufferViews': views, 'buffers': [{'byteLength': len(blob)}],
    }
    if used:
        doc['extensionsUsed'] = used
    return _pack_glb(doc, bytes(blob))


def _base_colour(scene):
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            texture = node.appearance.material.baseTexture
            return texture.image.convert('RGB').getpixel((4, 4)) if texture else None
        stack.extend(getattr(node, 'children', None) or [])
    raise AssertionError('no Shape in the loaded scene')


@pytest.fixture(autouse=True)
def _fresh_textures():
    gtextures.forget_shared_textures()
    yield
    gtextures.forget_shared_textures()


avif = pytest.mark.skipif(not features.check('avif'),
                          reason='this Pillow does not decode AVIF')


@avif
class TestAvif:
    def test_avif_image_is_preferred_to_the_fallback(self):
        doc = _document([('image/png', _encoded(RED, 'PNG')),
                         ('image/avif', _encoded(GREEN, 'AVIF'))],
                        {'source': 0, 'extensions': {'EXT_texture_avif': {'source': 1}}})
        red, green, blue = _base_colour(load_gltf(doc))
        assert green > 200 and red < 60

    def test_avif_as_the_only_source(self):
        doc = _document([('image/avif', _encoded(BLUE, 'AVIF'))],
                        {'extensions': {'EXT_texture_avif': {'source': 0}}})
        red, green, blue = _base_colour(load_gltf(doc))
        assert blue > 200 and red < 60

    def test_fallback_where_pillow_cannot_decode_avif(self, monkeypatch):
        monkeypatch.setattr(gtextures, 'decodes', lambda mime: mime != 'image/avif')
        doc = _document([('image/png', _encoded(RED, 'PNG')),
                         ('image/avif', _encoded(GREEN, 'AVIF'))],
                        {'source': 0, 'extensions': {'EXT_texture_avif': {'source': 1}}})
        assert _base_colour(load_gltf(doc)) == RED


class TestWebp:
    def test_webp_image_is_preferred_to_the_fallback(self):
        doc = _document([('image/png', _encoded(RED, 'PNG')),
                         ('image/webp', _encoded(GREEN, 'WEBP'))],
                        {'source': 0, 'extensions': {'EXT_texture_webp': {'source': 1}}})
        red, green, blue = _base_colour(load_gltf(doc))
        assert green > 200 and red < 60

    def test_basisu_falls_back_to_the_core_source(self):
        doc = _document([('image/png', _encoded(RED, 'PNG')),
                         ('image/ktx2', b'\xabKTX 20\xbb\r\n\x1a\n')],
                        {'source': 0, 'extensions': {'KHR_texture_basisu': {'source': 1}}})
        assert _base_colour(load_gltf(doc)) == RED


class TestDecodes:
    def test_core_formats(self):
        assert gtextures.decodes('image/png') and gtextures.decodes('image/jpeg')

    def test_unknown_format(self):
        assert not gtextures.decodes('image/ktx2')


def _textured_mesh(image):
    material = PhysicalMaterial(baseTexture=image)
    return PBRMesh(positions=TRIANGLE, texcoords=UV,
                   appearance=Appearance(material=material))


class TestWriting:
    @pytest.mark.parametrize('mime, format, extension', [
        pytest.param('image/avif', 'AVIF', 'EXT_texture_avif', marks=avif),
        ('image/webp', 'WEBP', 'EXT_texture_webp')])
    def test_an_encoded_image_in_an_extension_format(self, mime, format, extension):
        image = EncodedImage(_encoded(GREEN, format), mime_type=mime)
        writer = GLTFWriter()
        writer.add_node(SceneNode(mesh=_textured_mesh(image)))
        document = writer.document()
        (texture,) = document['textures']
        assert 'source' not in texture
        assert texture['extensions'][extension]['source'] == 0
        assert extension in document['extensionsUsed']
        assert extension in document['extensionsRequired']
        red, green, blue = _base_colour(load_gltf(writer.to_glb()))
        assert green > 200 and red < 60

    def test_a_png_needs_no_extension(self):
        image = EncodedImage(_encoded(RED, 'PNG'), mime_type='image/png')
        writer = GLTFWriter()
        writer.add_node(SceneNode(mesh=_textured_mesh(image)))
        document = writer.document()
        assert document['textures'][0]['source'] == 0
        assert 'extensionsRequired' not in document

    def test_encoded_image_from_an_avif_path(self, tmp_path):
        path = tmp_path / 'green.avif'
        path.write_bytes(b'not decoded here')
        assert EncodedImage.from_path(str(path)).mime_type == 'image/avif'
