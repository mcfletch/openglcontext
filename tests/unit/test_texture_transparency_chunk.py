"""A PNG's transparent colour (its tRNS chunk) is the texture's alpha.

Pillow reads such an image as greyscale, RGB or palette with the transparent
value in ``info['transparency']``; the texture stores it with an alpha
channel, transparent where the image has that value.
"""
import pytest
from PIL import Image

from OpenGLContext.texture import Texture


def stored(image):
    return Texture.ensureRGB(Texture.__new__(Texture), image)


@pytest.mark.parametrize('mode, transparent, opaque, expected_mode', [
    ('L', 255, 40, 'LA'),
    ('RGB', (255, 0, 0), (0, 0, 255), 'RGBA'),
])
def test_the_transparent_value_has_no_alpha(mode, transparent, opaque, expected_mode):
    image = Image.new(mode, (2, 1), opaque)
    image.putpixel((0, 0), transparent)
    image.info['transparency'] = transparent
    found = stored(image)
    assert found.mode == expected_mode
    assert found.getpixel((0, 0))[-1] == 0
    assert found.getpixel((1, 0))[-1] == 255


def test_a_palette_keeps_its_transparent_entry():
    image = Image.new('P', (2, 1), 1)
    image.putpalette([255, 0, 0, 0, 0, 255] + [0] * 762)
    image.putpixel((0, 0), 0)
    image.info['transparency'] = 0
    found = stored(image)
    assert found.mode == 'RGBA'
    assert found.getpixel((0, 0))[3] == 0 and found.getpixel((1, 0)) == (0, 0, 255, 255)


def test_an_image_without_one_is_unchanged():
    image = Image.new('L', (2, 1), 40)
    assert stored(image) is image
    palette = Image.new('P', (2, 1), 0)
    assert stored(palette).mode == 'RGB'
