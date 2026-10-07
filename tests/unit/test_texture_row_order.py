"""Which row of an image each kind of texture holds first.

A 2D texture's first row is t=0. VRML97 and X3D put texture coordinate (0, 0)
at an image's lower left, so an ImageTexture holds the bottom row first; glTF
puts it at the upper left, so an ImageDataTexture (glTF's images, and the
images the engine generates) holds the top row first. A cube map face's first
row is the top of the image, as GL's cube map faces are laid out.
"""
import types

import numpy as np
from OpenGL import GL
from PIL import Image

from OpenGLContext.texture import CubeTexture, Texture
from OpenGLContext.texturecache import TextureCache

TOP, BOTTOM = (255, 0, 0), (0, 0, 255)


def top_and_bottom(size=(4, 4)):
    """An image red in its top half and blue in its bottom half"""
    image = Image.new('RGB', size, BOTTOM)
    image.paste(TOP, (0, 0, size[0], size[1] // 2))
    return image


def rows(target, binding, texture):
    GL.glBindTexture(binding, texture)
    try:
        GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
        data = GL.glGetTexImage(target, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    finally:
        GL.glBindTexture(binding, 0)
    return np.frombuffer(bytes(data), np.uint8).reshape(4, 4, 3)


def test_a_2d_texture_holds_the_bottom_of_the_image_first(gl_context):
    tex = Texture(top_and_bottom())
    pixels = rows(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_2D, tex.texture)
    assert tuple(pixels[0, 0]) == BOTTOM
    assert tuple(pixels[-1, 0]) == TOP


def test_a_cube_face_holds_the_top_of_the_image_first(gl_context):
    faces = {face: top_and_bottom() for face in CubeTexture.CUBE_NAME_MAP}
    tex = CubeTexture(faces)
    pixels = rows(GL.GL_TEXTURE_CUBE_MAP_POSITIVE_Z, GL.GL_TEXTURE_CUBE_MAP, tex.texture)
    assert tuple(pixels[0, 0]) == TOP
    assert tuple(pixels[-1, 0]) == BOTTOM


def test_an_image_and_a_pixeltexture_of_it_agree(gl_context):
    """SFImage lists pixels bottom row first; a PixelTexture stores them as listed"""
    from OpenGLContext.scenegraph.basenodes import PixelTexture  # noqa: PLC0415 kept with its use
    red, blue = 0xFF0000, 0x0000FF
    node = PixelTexture(image=[4, 4, 3] + [blue] * 8 + [red] * 8)
    from_pixels = node.createTexture(node.image)
    from_image = Texture(top_and_bottom())
    assert np.array_equal(rows(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_2D, from_pixels.texture),
                          rows(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_2D, from_image.texture))


def node_rows(node, cache):
    mode = types.SimpleNamespace(context=types.SimpleNamespace(textureCache=cache),
                                 shader_mode=True)
    tex = node.createTexture(node.image, mode=mode)
    return rows(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_2D, tex.texture)


def test_each_node_holds_the_row_its_coordinates_start_from(gl_context):
    from OpenGLContext.scenegraph.basenodes import ImageTexture  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.imagedata import ImageDataTexture  # noqa: PLC0415 kept with its use
    image = top_and_bottom()
    image.info['url'] = 'shared.png'
    cache = TextureCache()
    vrml = node_rows(ImageTexture(image=image), cache)
    gltf = node_rows(ImageDataTexture(image=image), cache)
    assert tuple(vrml[0, 0]) == BOTTOM, 'X3D: (0, 0) is the lower left'
    assert tuple(gltf[0, 0]) == TOP, 'glTF: (0, 0) is the upper left'
