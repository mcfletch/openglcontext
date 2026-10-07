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

from vrml import cache
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.imagetexture import PILImage, _Texture
from OpenGLContext.scenegraph.sampler import sampler_of, texture_properties

__all__ = ['ImageDataTexture', 'ROUGHNESS_KEY', 'green_mean', 'sampler_of', 'texture_properties']

#: The key an image's mean roughness is kept under in vrml's cache.
ROUGHNESS_KEY = 'mean-roughness'


class ImageDataTexture(_Texture, x3d.X3DTexture2DNode):
    """An X3D 2D texture whose image is a decoded PIL image"""

    PROTO = 'ImageDataTexture'
    image = PILImage(' image', 1, None)

    def x3dEquivalent(self) -> Any:
        """An X3D `ImageTexture` of the image as a PNG `data:` URL, for the X3D writers"""
        import io  # noqa: PLC0415 only an X3D writer asks
        stream = io.BytesIO()
        self.image.save(stream, 'PNG')
        return self.x3dTexture('image/png', stream.getvalue())

    def x3dTexture(self, mime_type: str, data: bytes) -> Any:
        """An X3D `ImageTexture` of encoded image bytes, sampled as this texture is"""
        import base64  # noqa: PLC0415 only an X3D writer asks
        url = 'data:%s;base64,%s' % (mime_type, base64.b64encode(data).decode('ascii'))
        return x3d.ImageTexture(url=[url], repeatS=self.repeatS, repeatT=self.repeatT,
                                textureProperties=self.textureProperties)

    def sampler(self) -> "dict[str, str]":
        """The X3D boundary modes and filters the texture is sampled with"""
        return sampler_of(self)

    def mean_roughness(self) -> float:
        """The mean of the image's green channel, from 0 to 1

        The green channel is roughness in a glTF metallic-roughness map.
        Worked out from a copy of at most 256 texels a side, and kept in
        vrml's cache under :data:`ROUGHNESS_KEY` until `image` is set.
        """
        found: Optional[float] = cache.CACHE.getData(self, ROUGHNESS_KEY)
        if found is None:
            found = green_mean(self.image)
            cache.CACHE.holder(self, found, ROUGHNESS_KEY).depend(self, type(self).image)
        return found


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
