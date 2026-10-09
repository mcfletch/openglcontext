"""EXT_texture_video: a texture whose source is a movie, drawn as a MovieTexture.

The extension (Draft, github.com/takahirox/EXT_texture_video, MIT) lists
videos in the document's ``extensions`` by ``uri`` or ``bufferView`` and names
one from a texture's ``extensions``; the core ``source`` is the fallback.
``tests/resources/colours.mp4`` is eight solid colours, a quarter of a second
each.
"""
import base64
import io
import os
import shutil

import numpy as np
import pytest

pytest.importorskip("pygltflib")
Image = pytest.importorskip("PIL.Image")

from OpenGLContext.events import systemtime
from OpenGLContext.loaders import background
from OpenGLContext.loaders.gltf import load_gltf
from OpenGLContext.loaders.gltf.writer import _pack_glb
from OpenGLContext.scenegraph.movietexture import MovieTexture

COLOURS_MOVIE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'resources', 'colours.mp4')
QUAD = np.array([[-5, -5, 0], [5, -5, 0], [5, 5, 0], [-5, 5, 0]], np.float32)
UV = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], np.float32)
INDICES = np.array([0, 1, 2, 0, 2, 3], np.uint16)


def _png_uri(colour):
    out = io.BytesIO()
    Image.new('RGB', (2, 2), colour).save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()


def _document(video, texture_video=0):
    """A quad, unlit, its colour a texture with a red image as the fallback and
    ``video`` (a dict, or bytes for a bufferView) as the video."""
    blob = bytearray(QUAD.tobytes() + UV.tobytes() + INDICES.tobytes())
    views = [{'buffer': 0, 'byteOffset': 0, 'byteLength': 48},
             {'buffer': 0, 'byteOffset': 48, 'byteLength': 32},
             {'buffer': 0, 'byteOffset': 80, 'byteLength': 12}]
    if isinstance(video, bytes):
        blob.extend(b'\0' * (-len(blob) % 4))
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(video)})
        blob.extend(video)
        video = {'bufferView': 3, 'mimeType': 'video/mp4'}
    doc = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['EXT_texture_video', 'KHR_materials_unlit'],
        'extensions': {'EXT_texture_video': {'videos': [video]}},
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                    'indices': 2, 'material': 0}]}],
        'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}},
                       'extensions': {'KHR_materials_unlit': {}}}],
        'textures': [{'source': 0,
                      'extensions': {'EXT_texture_video': {'source': texture_video}}}],
        'images': [{'uri': _png_uri((255, 0, 0))}],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 4,
             'min': [-5, -5, 0], 'max': [5, 5, 0]},
            {'bufferView': 1, 'componentType': 5126, 'type': 'VEC2', 'count': 4},
            {'bufferView': 2, 'componentType': 5123, 'type': 'SCALAR', 'count': 6}],
        'bufferViews': views, 'buffers': [{'byteLength': len(blob)}],
    }
    return _pack_glb(doc, bytes(blob))


def _texture(scene):
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            return node.appearance.material.emissiveTexture
        stack.extend(getattr(node, 'children', None) or [])
    raise AssertionError('no shape')


def test_a_video_by_uri_is_a_looping_movie_texture(tmp_path):
    shutil.copy(COLOURS_MOVIE, tmp_path / 'clip.mp4')
    scene = load_gltf(_document({'uri': 'clip.mp4'}), base_dir=str(tmp_path))
    texture = _texture(scene)
    assert isinstance(texture, MovieTexture)
    assert texture.loop
    assert [os.path.normpath(entry) for entry in texture.url] == [
        os.path.normpath(str(tmp_path / 'clip.mp4'))]


def test_a_video_in_a_buffer_view_is_written_once_for_the_decoder(tmp_path):
    data = open(COLOURS_MOVIE, 'rb').read()
    first = _texture(load_gltf(_document(data)))
    second = _texture(load_gltf(_document(data)))
    assert isinstance(first, MovieTexture)
    (path,) = first.url
    assert open(path, 'rb').read() == data
    assert list(second.url) == [path]


def test_a_video_reference_outside_the_document_falls_back(tmp_path):
    scene = load_gltf(_document({'uri': '../elsewhere/clip.mp4'}), base_dir=str(tmp_path))
    assert not isinstance(_texture(scene), MovieTexture)


@pytest.mark.parametrize('video, index', [({'uri': 'clip.mp4'}, 3), ({}, 0),
                                          ({'bufferView': 9}, 0)])
def test_a_video_that_is_not_there_falls_back_to_the_image(tmp_path, video, index):
    texture = _texture(load_gltf(_document(video, index), base_dir=str(tmp_path)))
    assert not isinstance(texture, MovieTexture)
    assert texture.image.convert('RGB').getpixel((0, 0)) == (255, 0, 0)


def test_the_movie_is_drawn(gl_context, tmp_path):
    pytest.importorskip('pyopengl_video')
    from pyopengl_video import decoder as decoders
    from OpenGLContext.testing.scenes import drawn_image, scene_context

    class Clock:
        now = 0.6                       # the third colour, blue

        def __call__(self):
            return self.now
    previous = systemtime.setTimeSource(Clock())
    try:
        shutil.copy(COLOURS_MOVIE, tmp_path / 'clip.mp4')
        scene = load_gltf(_document({'uri': 'clip.mp4'}), base_dir=str(tmp_path))
        assert background.wait_for_idle(20.0)
        with scene_context([scene.group], size=(32, 32)) as context:
            if not list(decoders.available_backends()):
                pytest.skip('no video decoder for this GL context')
            drawn_image(context)
            found = drawn_image(context)[16, 16, :3].astype(float) / 255.0
    finally:
        systemtime.setTimeSource(previous)
    assert found[2] > 0.6 and found[0] < 0.3 and found[1] < 0.3, found


def test_a_movie_texture_is_written_as_a_video(tmp_path):
    from OpenGLContext.loaders.gltf import GLTFWriter, SceneNode
    from OpenGLContext.loaders.gltf.textures import VIDEO_EXTENSION
    shutil.copy(COLOURS_MOVIE, tmp_path / 'clip.mp4')
    scene = load_gltf(_document({'uri': 'clip.mp4'}), base_dir=str(tmp_path))
    mesh = None
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            mesh = node.geometry
        stack.extend(getattr(node, 'children', None) or [])
    writer = GLTFWriter()
    writer.add_node(SceneNode(mesh=mesh))
    document = writer.document()
    (texture,) = document['textures']
    assert texture['extensions'][VIDEO_EXTENSION] == {'source': 0}
    (video,) = document['extensions'][VIDEO_EXTENSION]['videos']
    assert os.path.normpath(video['uri']) == os.path.normpath(str(tmp_path / 'clip.mp4'))
    assert VIDEO_EXTENSION in document['extensionsRequired']
    # Written beside the video, the reference is relative to the file.
    writer.write(str(tmp_path / 'screen.glb'))
    again = load_gltf(str(tmp_path / 'screen.glb'))
    assert isinstance(_texture(again), MovieTexture)
