"""One image, loaded twice, is one texture.

A streamed world is hundreds of files, and the tree in one tile is the same tree
as the tree in the next: the same bark, byte for byte, embedded in every tile
that has a tree in it. Loaded as a texture each, that is a hundred copies of one
image in video memory -- and worse, a hundred *different* textures, which means
a hundred draws where there should be one, because a single draw can only bind
one texture.

So the loader keys its textures on what is in them. Held weakly, because a
texture that nothing is drawing is a texture the world has finished with.
"""
import base64
import gc
import io
import json

import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import textures


def _png(colour=(200, 120, 40), size=8):
    from PIL import Image
    image = Image.new('RGB', (size, size), colour)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def _document(png, base_colour=(1.0, 1.0, 1.0, 1.0)):
    positions = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype='<f4')
    uv = np.array([(0, 0), (1, 0), (0, 1)], dtype='<f4')
    blob = positions.tobytes() + uv.tobytes() + png
    at = len(positions.tobytes()) + len(uv.tobytes())
    return {
        'asset': {'version': '2.0'},
        'buffers': [{'byteLength': len(blob),
                     'uri': 'data:application/octet-stream;base64,'
                            + base64.b64encode(blob).decode('ascii')}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': positions.nbytes},
            {'buffer': 0, 'byteOffset': positions.nbytes, 'byteLength': uv.nbytes},
            {'buffer': 0, 'byteOffset': at, 'byteLength': len(png)},
        ],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
             'min': [0, 0, 0], 'max': [1, 1, 0]},
            {'bufferView': 1, 'componentType': 5126, 'count': 3, 'type': 'VEC2'},
        ],
        'images': [{'bufferView': 2, 'mimeType': 'image/png'}],
        'samplers': [{}],
        'textures': [{'source': 0, 'sampler': 0}],
        'materials': [{'pbrMetallicRoughness': {
            'baseColorTexture': {'index': 0},
            'baseColorFactor': list(base_colour)}}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                    'material': 0}]}],
        'nodes': [{'mesh': 0}],
        'scenes': [{'nodes': [0]}],
        'scene': 0,
    }


def _write(tmp_path, name, png, **named):
    path = tmp_path / name
    path.write_text(json.dumps(_document(png, **named)))
    return str(path)


def _texture_of(scene):
    from OpenGLContext.scenegraph.shape import Shape
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if isinstance(node, Shape) and node.appearance is not None:
            material = node.appearance.material
            found = getattr(material, 'textures', None)
            if found:
                return next(iter(found.values()))
        stack.extend(getattr(node, 'children', None) or ())
    return None


@pytest.fixture(autouse=True)
def _forget_textures():
    """Each test starts with nothing remembered, and leaves nothing behind."""
    textures.forget_shared_textures()
    yield
    textures.forget_shared_textures()


class TestTheSameImageTwice:
    def test_two_files_with_one_image_share_one_texture(self, tmp_path) -> None:
        png = _png()
        first = _texture_of(gltf.load_gltf(_write(tmp_path, 'a.gltf', png)))
        second = _texture_of(gltf.load_gltf(_write(tmp_path, 'b.gltf', png)))
        assert first is not None
        assert first is second

    def test_which_is_what_lets_them_batch(self, tmp_path) -> None:
        """The point of it: one texture is one draw."""
        from OpenGLContext.passes.instancing import geometry_content_key
        from OpenGLContext.scenegraph.shape import Shape
        png = _png()
        scenes = [gltf.load_gltf(_write(tmp_path, name, png))
                  for name in ('a.gltf', 'b.gltf')]
        keys = []
        for scene in scenes:
            stack = [scene.group]
            while stack:
                node = stack.pop()
                if isinstance(node, Shape) and node.geometry is not None:
                    keys.append(geometry_content_key([node]))
                stack.extend(getattr(node, 'children', None) or ())
        assert len(keys) == 2 and keys[0] == keys[1]

    def test_different_images_are_different_textures(self, tmp_path) -> None:
        one = _texture_of(gltf.load_gltf(
            _write(tmp_path, 'a.gltf', _png(colour=(200, 120, 40)))))
        two = _texture_of(gltf.load_gltf(
            _write(tmp_path, 'b.gltf', _png(colour=(20, 200, 90)))))
        assert one is not two

    def test_the_pixels_are_the_ones_that_were_written(self, tmp_path) -> None:
        texture = _texture_of(gltf.load_gltf(
            _write(tmp_path, 'a.gltf', _png(colour=(200, 120, 40)))))
        assert texture.image.getpixel((0, 0))[:3] == (200, 120, 40)

    def test_a_second_load_still_gets_its_pixels(self, tmp_path) -> None:
        png = _png(colour=(200, 120, 40))
        gltf.load_gltf(_write(tmp_path, 'a.gltf', png))
        second = _texture_of(gltf.load_gltf(_write(tmp_path, 'b.gltf', png)))
        assert second.image.getpixel((0, 0))[:3] == (200, 120, 40)


class TestWhatIsNotShared:
    def test_the_same_image_in_two_colour_spaces_is_not_one_texture(
            self, tmp_path) -> None:
        """A base colour is sRGB and a roughness map is linear; the same file
        used as both is two textures, because they are read differently."""
        png = _png()
        path = _write(tmp_path, 'a.gltf', png)
        document = json.loads(open(path).read())
        document['materials'][0]['pbrMetallicRoughness'][
            'metallicRoughnessTexture'] = {'index': 0}
        open(path, 'w').write(json.dumps(document))
        scene = gltf.load_gltf(path)
        from OpenGLContext.scenegraph.shape import Shape
        stack, found = [scene.group], None
        while stack:
            node = stack.pop()
            if isinstance(node, Shape) and node.appearance is not None:
                maps = getattr(node.appearance.material, 'textures', None)
                if maps:
                    found = maps
            stack.extend(getattr(node, 'children', None) or ())
        assert found is not None and len(found) == 2
        assert found['baseColor'] is not found['metallicRoughness']

    def test_the_same_image_with_different_wrapping_is_not_one_texture(
            self, tmp_path) -> None:
        png = _png()
        plain = _write(tmp_path, 'a.gltf', png)
        clamped = _write(tmp_path, 'b.gltf', png)
        document = json.loads(open(clamped).read())
        document['samplers'][0] = {'wrapS': 33071, 'wrapT': 33071}
        open(clamped, 'w').write(json.dumps(document))
        assert _texture_of(gltf.load_gltf(plain)) \
            is not _texture_of(gltf.load_gltf(clamped))


class TestNotHoldingOnForever:
    def test_a_texture_nothing_is_drawing_is_let_go(self, tmp_path) -> None:
        """A world streaming tiles for an hour must not accumulate every image
        it has ever seen."""
        png = _png()
        scene = gltf.load_gltf(_write(tmp_path, 'a.gltf', png))
        assert textures.shared_texture_count() == 1
        del scene
        gc.collect()
        assert textures.shared_texture_count() == 0

    def test_one_still_in_use_is_kept(self, tmp_path) -> None:
        png = _png()
        scene = gltf.load_gltf(_write(tmp_path, 'a.gltf', png))
        gc.collect()
        assert textures.shared_texture_count() == 1
        assert scene is not None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
