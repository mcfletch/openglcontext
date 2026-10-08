"""How a 2D texture is sampled: X3D's boundary modes and filters as GL state

An X3D 2D texture states its sampler with `repeatS`/`repeatT`, or with a
`TextureProperties` node that names boundary modes and filters in X3D's
terms. `sampler_of` reads either into one dictionary; `apply_sampler` sets
it on a GL texture object.

A document's texture with no `TextureProperties` whose image is smaller than
:data:`SMALL_IMAGE` texels on its longer side is sampled from its nearest
texel, magnified or minified, so a `PixelTexture`'s few texels are drawn as
crisp squares; X3D leaves the default filters to the browser, and this is
X_ITE's choice too. A texture made in code takes the engine's filters
whatever its size.
"""
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

#: Texels on the longer side below which a document's image with no
#: TextureProperties is sampled from its nearest texel.
SMALL_IMAGE = 16


def sampler_of(texture: Any, size: Optional[tuple[int, int]] = None) -> "dict[str, str]":
    """The X3D boundary modes and filters an X3D 2D texture is sampled with

    From its `textureProperties` node where there is one, else from
    `repeatS`/`repeatT` with the default filters, or with NEAREST_PIXEL for a
    document's image `size` (width, height) smaller than :data:`SMALL_IMAGE`.
    """
    properties = getattr(texture, 'textureProperties', None)
    if properties:
        return {
            'wrap_s': str(properties.boundaryModeS),
            'wrap_t': str(properties.boundaryModeT),
            'minification': str(properties.minificationFilter),
            'magnification': str(properties.magnificationFilter),
        }
    from OpenGLContext.lighting import in_document  # noqa: PLC0415 lighting reads the scene classes
    small = size is not None and max(size) < SMALL_IMAGE and in_document(texture)
    filter_ = 'NEAREST_PIXEL' if small else 'DEFAULT'
    return {
        'wrap_s': 'REPEAT' if getattr(texture, 'repeatS', True) else 'CLAMP_TO_EDGE',
        'wrap_t': 'REPEAT' if getattr(texture, 'repeatT', True) else 'CLAMP_TO_EDGE',
        'minification': filter_,
        'magnification': filter_,
    }


def texture_properties(wrap_s: str = 'REPEAT', wrap_t: str = 'REPEAT',
                       minification: str = 'DEFAULT',
                       magnification: str = 'DEFAULT') -> Any:
    """A TextureProperties node for a sampler given in X3D's terms"""
    return x3d.TextureProperties(
        boundaryModeS=wrap_s, boundaryModeT=wrap_t,
        minificationFilter=minification, magnificationFilter=magnification,
        generateMipMaps=minification not in ('AVG_PIXEL', 'NEAREST_PIXEL'),
    )


def apply_sampler(texture: Any, sampler: "dict[str, str]") -> None:
    """Set a sampler (as `sampler_of` gives it) on a GL texture object, with mipmaps"""
    from OpenGL import GL  # noqa: PLC0415 GL only when a texture is compiled
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
                       getattr(GL, MAGNIFICATION.get(sampler['magnification'], 'GL_LINEAR')))
