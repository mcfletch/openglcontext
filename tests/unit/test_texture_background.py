"""X3D's TextureBackground: a background whose six sides are texture nodes.

Drawn as the engine's Background is: the sky and ground colours on a sphere,
and each side that has an image on a cube over it. It binds as any background
does.
"""
import pytest
from vrml.x3d import binding
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph.texturebackground import TextureBackground


def test_it_is_the_engines_and_bindable():
    assert prototypes()['TextureBackground'] is TextureBackground
    assert issubclass(TextureBackground, binding.Bindable)


def test_its_sides_are_its_texture_fields():
    from PIL import Image  # noqa: PLC0415 kept with its use

    from OpenGLContext.scenegraph.imagetexture import ImageTexture  # noqa: PLC0415 kept with its use
    loaded, waiting = ImageTexture(), ImageTexture()
    loaded.setImage(Image.new('RGB', (2, 2)))
    background = TextureBackground(frontTexture=loaded, backTexture=waiting)
    assert background.front is loaded
    assert not background.back.components
    assert not background.top.components


def test_its_cache_depends_on_its_texture_fields():
    front = x3d.ImageTexture()
    background = TextureBackground(frontTexture=front)
    names = {(node is background, name) for node, name in background.sideDependencies()}
    assert (True, 'frontTexture') in names and (True, 'backTexture') in names


def test_a_pixel_texture_side_is_decoded_once_until_its_image_changes(monkeypatch):
    from OpenGLContext.scenegraph import texturebackground  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.memo import check_memo_inputs  # noqa: PLC0415 kept with its use
    decoded = []
    real = texturebackground.sfimage_pixels

    def counting(*args):
        decoded.append(args)
        return real(*args)

    monkeypatch.setattr(texturebackground, 'sfimage_pixels', counting)
    side = x3d.PixelTexture(image=[1, 1, 3, 0xFF0000])
    background = TextureBackground(frontTexture=side)
    for _frame in range(3):
        assert background.hasImages()
    assert len(decoded) == 1

    def ask():
        return background.front.image.getpixel((0, 0))

    check_memo_inputs(ask, [
        ('pixels.image', lambda: setattr(side, 'image', [1, 1, 3, 0x00FF00])),
        ('frontTexture', lambda: setattr(
            background, 'frontTexture', x3d.PixelTexture(image=[1, 1, 3, 0x0000FF]))),
    ], fresh=lambda: texturebackground.decode_side(background.frontTexture).image.getpixel((0, 0)))


SIDES = ' '.join('%sTexture' % side for side in ('front', 'back', 'left', 'right', 'top', 'bottom'))


def drawn(content):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'<X3D version="4.0"><Scene><Viewpoint position="0 0 0"/>'
                         + content + b'</Scene></X3D>', 'scene.x3d')
    with scene_context(scene, size=(32, 32)) as context:
        drawn_image(context)
        return drawn_image(context)[16, 16].astype(int)


def test_the_sky_colour_is_drawn(gl_context):
    colour = drawn(b'<TextureBackground skyColor="0 0 1"/>')
    assert colour[2] > colour[0] + 100


def test_the_sides_are_drawn_over_the_sky(gl_context):
    sides = b''.join(
        b'<PixelTexture containerField="%sTexture" image="1 1 3 0x00FF00"/>' % side
        for side in (b'front', b'back', b'left', b'right', b'top', b'bottom'))
    colour = drawn(b'<TextureBackground skyColor="0 0 1">' + sides + b'</TextureBackground>')
    assert colour[1] > colour[2] + 100


@pytest.mark.parametrize('limit', [b'0.5', b'2'])
def test_the_sides_are_drawn_whatever_the_far_plane(gl_context, limit):
    """The sides are at the far plane, so a short visibilityLimit keeps them"""
    sides = b''.join(
        b'<PixelTexture containerField="%sTexture" image="1 1 3 0x00FF00"/>' % side
        for side in (b'front', b'back', b'left', b'right', b'top', b'bottom'))
    colour = drawn(b'<NavigationInfo visibilityLimit="' + limit + b'"/>'
                   b'<TextureBackground skyColor="0 0 1">' + sides + b'</TextureBackground>')
    assert colour[1] > colour[2] + 100
