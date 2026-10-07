"""X3D's TextureBackground: a background whose six sides are texture nodes

Drawn as the engine's Background is (:class:`~OpenGLContext.scenegraph.background.SkyAndCube`):
the sky and ground colours on a sphere, and the six sides as a cube over it
once every side has an image. A side is an ImageTexture, drawn once its image
has loaded, or a PixelTexture; any other texture node, or none, leaves the
cube undrawn. ``transparency`` is not read.
"""
from typing import Any, NamedTuple, Optional

from PIL import Image
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.background import SkyAndCube
from OpenGLContext.scenegraph.imagetexture import sfimage_pixels

__all__ = ['SideImage', 'TextureBackground']

#: Each side the cube reads, to the TextureBackground field it is held in.
SIDES = {side: side + 'Texture' for side in ('right', 'left', 'top', 'bottom', 'front', 'back')}


class SideImage(NamedTuple):
    """A side's image as the cube reads it: its component count and its PIL image"""

    components: int
    image: Optional[Image.Image]


#: A side with no image.
NO_IMAGE = SideImage(0, None)

#: The PIL mode for an SFImage of each component count.
_MODES = {1: 'L', 2: 'LA', 3: 'RGB', 4: 'RGBA'}


def side_image(texture: Any) -> Any:
    """What the cube reads from a side's texture node

    An ImageTexture is read as it is; a PixelTexture's SFImage is decoded,
    top row first as PIL holds an image.
    """
    if not texture:
        return NO_IMAGE
    if isinstance(texture, x3d.PixelTexture):
        decoded = sfimage_pixels(texture.image, texture)
        if decoded is None:
            return NO_IMAGE
        components, width, height, data = decoded
        image = Image.frombytes(_MODES[components], (width, height), data)
        return SideImage(components, image.transpose(Image.Transpose.FLIP_TOP_BOTTOM))
    if getattr(texture, 'components', 0) and getattr(texture, 'image', None) is not None:
        return texture
    return NO_IMAGE


def _side(name: str) -> property:
    field_name = SIDES[name]

    def read(self: Any) -> Any:
        return side_image(getattr(self, field_name))
    return property(read, doc='The %s side, from `%s`' % (name, field_name))


class TextureBackground(SkyAndCube, x3d.TextureBackground):
    """X3D's TextureBackground

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/environmentalEffects.html#TextureBackground
    """

    PROTO = 'TextureBackground'

    right = _side('right')
    left = _side('left')
    top = _side('top')
    bottom = _side('bottom')
    front = _side('front')
    back = _side('back')

    def sideDependencies(self) -> list[tuple[Any, str]]:
        """Its six texture fields, and the image of each side's texture node"""
        found: list[tuple[Any, str]] = [(self, name) for name in SIDES.values()]
        for name in SIDES.values():
            texture = getattr(self, name)
            if texture and hasattr(type(texture), 'image'):
                found.append((texture, 'image'))
        return found
