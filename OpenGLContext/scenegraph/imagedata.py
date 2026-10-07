"""ImageDataTexture: a texture node for an image already decoded in memory

A glTF buffer view, an image `surfaces.py` generates, a lightmap a baker
wrote: an image that has no URL of its own. The node is an ordinary X3D 2D
texture, so it goes wherever an `ImageTexture` does (a `PhysicalMaterial`
texture field, an `Appearance`), with `repeatS`/`repeatT` and a
`TextureProperties` for the sampler. It is drawn as the engine's
`ImageTexture` is: compiled through the context's texture cache and held in
the context's node cache until its image or sampler is set.
"""
from typing import Any, Optional

from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.imagetexture import PILImage, _Texture
from OpenGLContext.scenegraph.sampler import sampler_of, texture_properties

__all__ = ['ImageDataTexture', 'green_mean', 'sampler_of', 'texture_properties']


class ImageDataTexture(_Texture, x3d.X3DTexture2DNode):
    """An X3D 2D texture whose image is a decoded PIL image"""

    PROTO = 'ImageDataTexture'
    image = PILImage(' image', 1, None)

    def sampler(self) -> "dict[str, str]":
        """The X3D boundary modes and filters the texture is sampled with"""
        return sampler_of(self)

    def mean_roughness(self) -> float:
        """The mean of the image's green channel, from 0 to 1

        The green channel is roughness in a glTF metallic-roughness map.
        Worked out from a copy of at most 256 texels a side, once per image:
        a new `image` is measured again.
        """
        image = self.image
        known: Optional[tuple[Any, float]] = self.__dict__.get('_mean_roughness')
        if known is None or known[0] is not image:
            known = self.__dict__['_mean_roughness'] = (image, green_mean(image))
        return known[1]


def green_mean(image: Any) -> float:
    """The mean of a PIL image's green channel, from 0 to 1"""
    from PIL import ImageStat  # noqa: PLC0415 PIL only when a map is measured
    if image.mode not in ('RGB', 'RGBA', 'RGBX'):
        image = image.convert('RGB')
    # The channel alone, so an alpha of 0 weighs nothing into the reduction.
    green = image.getchannel('G')
    factor = max(1, max(green.size) // 256)
    if factor > 1:
        green = green.reduce(factor)
    return float(ImageStat.Stat(green).mean[0]) / 255.0
