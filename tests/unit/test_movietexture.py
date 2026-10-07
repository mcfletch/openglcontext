"""MovieTexture: kept with its fields, and a shape it textures drawn untextured.

Nothing decodes a MovieTexture's ``url``; the node answers the texture
protocol with nothing to bind, so the shape it is on is drawn and the rest of
the scene with it.
"""
import numpy as np

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph.basenodes import Appearance, Box, Material, Shape
from OpenGLContext.scenegraph.movietexture import MovieTexture


def test_it_is_the_engines():
    assert prototypes()['MovieTexture'] is MovieTexture


def test_it_binds_nothing():
    movie = MovieTexture(url=['movie.mpg'], loop=True)
    assert movie.cached(None) is None
    assert movie.render(lit=1, mode=None) is False
    movie.renderPost(mode=None)
    assert list(movie.url) == ['movie.mpg']


def test_a_shape_it_textures_sorts_as_untextured():
    appearance = Appearance(material=Material(), texture=MovieTexture())
    transparent, texture_token, _material = appearance.sortKey(None, np.identity(4))
    assert (transparent, texture_token) == (False, [])


def test_a_shape_it_textures_is_drawn(gl_context):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    shape = Shape(geometry=Box(size=(3, 3, 3)), appearance=Appearance(
        material=Material(diffuseColor=(1, 0, 0), emissiveColor=(1, 0, 0)),
        texture=MovieTexture(url=['movie.mpg'])))
    with scene_context([shape], size=(32, 32)) as context:
        image = drawn_image(context)
    assert image[16, 16, 0] > 150
