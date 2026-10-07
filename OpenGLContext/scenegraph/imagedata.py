"""ImageDataTexture: a texture node for an image already decoded in memory

A glTF buffer view, an image `surfaces.py` generates, a lightmap a baker
wrote: an image that has no URL of its own. The node is an ordinary X3D 2D
texture, so it goes wherever an `ImageTexture` does (a `PhysicalMaterial`
texture field, an `Appearance`), with `repeatS`/`repeatT` and a
`TextureProperties` for the sampler. The image is a PIL image held as the
`image` attribute; it is not a field, since no field type holds one.
"""
import weakref
from typing import Any, Optional

from vrml.x3d import nodes as x3d

#: X3D boundary modes as GL wrap modes. X3D's CLAMP is GL's CLAMP_TO_EDGE in a
#: core profile, which has no other clamp to the texture's edge.
WRAP_MODES = {
    'REPEAT': 'GL_REPEAT', 'MIRRORED_REPEAT': 'GL_MIRRORED_REPEAT',
    'CLAMP': 'GL_CLAMP_TO_EDGE', 'CLAMP_TO_EDGE': 'GL_CLAMP_TO_EDGE',
    'CLAMP_TO_BOUNDARY': 'GL_CLAMP_TO_BORDER',
}

#: X3D minification filters as GL filters; the rest (DEFAULT, FASTEST,
#: NICEST) take the engine's choice, trilinear.
MINIFICATION = {
    'AVG_PIXEL': 'GL_LINEAR', 'NEAREST_PIXEL': 'GL_NEAREST',
    'AVG_PIXEL_AVG_MIPMAP': 'GL_LINEAR_MIPMAP_LINEAR',
    'AVG_PIXEL_NEAREST_MIPMAP': 'GL_LINEAR_MIPMAP_NEAREST',
    'NEAREST_PIXEL_AVG_MIPMAP': 'GL_NEAREST_MIPMAP_LINEAR',
    'NEAREST_PIXEL_NEAREST_MIPMAP': 'GL_NEAREST_MIPMAP_NEAREST',
}

#: X3D magnification filters as GL filters; the rest take GL_LINEAR.
MAGNIFICATION = {'AVG_PIXEL': 'GL_LINEAR', 'NEAREST_PIXEL': 'GL_NEAREST'}


class ImageDataTexture(x3d.X3DTexture2DNode):
    """An X3D 2D texture whose image is a decoded PIL image"""

    PROTO = 'ImageDataTexture'

    def __init__(self, image: Any = None, **named: Any) -> None:
        super().__init__(**named)
        self._image = image
        #: The texture built for each context, forgotten with the context.
        self._per_context: "weakref.WeakKeyDictionary[Any, Any]" = \
            weakref.WeakKeyDictionary()
        #: The image :meth:`mean_roughness` was worked out for, and its answer.
        self._mean_roughness: Optional[tuple[Any, float]] = None

    @property
    def image(self) -> Any:
        """The PIL image, or None"""
        return self._image

    @image.setter
    def image(self, image: Any) -> None:
        self._image = image

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
        known = self._mean_roughness
        if known is None or known[0] is not image:
            known = self._mean_roughness = (image, green_mean(image))
        return known[1]

    def cached(self, mode: Any) -> Any:
        """The GL texture for the rendering context `mode` is drawing in"""
        context = mode.context
        texture = self._per_context.get(context)
        if texture is None:
            from OpenGLContext import texture as texture_module  # noqa: PLC0415 GL at first draw, not at import
            texture = texture_module.Texture(image=self.image)
            self._apply_sampler(texture)
            self._per_context[context] = texture
        return texture

    def _apply_sampler(self, texture: Any) -> None:
        """Set the sampler's wrap modes and filters, with mipmaps"""
        from OpenGL import GL  # noqa: PLC0415 GL at first draw, not at import
        sampler = self.sampler()
        GL.glBindTexture(GL.GL_TEXTURE_2D, texture.texture)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S,
                           getattr(GL, WRAP_MODES.get(sampler['wrap_s'], 'GL_REPEAT')))
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T,
                           getattr(GL, WRAP_MODES.get(sampler['wrap_t'], 'GL_REPEAT')))
        minification = getattr(GL, MINIFICATION.get(sampler['minification'],
                                                     'GL_LINEAR_MIPMAP_LINEAR'))
        try:
            GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        except GL.GLError:
            minification = GL.GL_LINEAR
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, minification)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER,
                           getattr(GL, MAGNIFICATION.get(sampler['magnification'],
                                                         'GL_LINEAR')))


def sampler_of(texture: Any) -> "dict[str, str]":
    """The X3D boundary modes and filters an X3D 2D texture is sampled with

    From its `textureProperties` node where there is one, else from
    `repeatS`/`repeatT` with the default filters.
    """
    properties = getattr(texture, 'textureProperties', None)
    if properties:
        return {
            'wrap_s': str(properties.boundaryModeS),
            'wrap_t': str(properties.boundaryModeT),
            'minification': str(properties.minificationFilter),
            'magnification': str(properties.magnificationFilter),
        }
    return {
        'wrap_s': 'REPEAT' if getattr(texture, 'repeatS', True) else 'CLAMP_TO_EDGE',
        'wrap_t': 'REPEAT' if getattr(texture, 'repeatT', True) else 'CLAMP_TO_EDGE',
        'minification': 'DEFAULT',
        'magnification': 'DEFAULT',
    }


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


def texture_properties(wrap_s: str = 'REPEAT', wrap_t: str = 'REPEAT',
                       minification: str = 'DEFAULT',
                       magnification: str = 'DEFAULT') -> Any:
    """A TextureProperties node for a sampler given in X3D's terms"""
    return x3d.TextureProperties(
        boundaryModeS=wrap_s, boundaryModeT=wrap_t,
        minificationFilter=minification, magnificationFilter=magnification,
        generateMipMaps=minification not in ('AVG_PIXEL', 'NEAREST_PIXEL'),
    )
