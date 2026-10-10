"""How a texture is sampled: X3D's boundary modes and filters as GL state

An X3D texture states its sampler with `repeatS`/`repeatT` (and a 3D
texture's `repeatR`), or with a `TextureProperties` node that names boundary
modes and filters in X3D's terms. `sampler_of` reads either into one
dictionary; `apply_sampler` sets it on a GL texture object of any target.

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

#: Each mipmapped GL minification filter (by enum) as the filter of its level
#: alone, for a texture with one level and no way to make more.
_WITHOUT_MIPMAPS = {0x2700: 0x2600, 0x2702: 0x2600,     # GL_NEAREST_MIPMAP_* -> GL_NEAREST
                    0x2701: 0x2601, 0x2703: 0x2601}     # GL_LINEAR_MIPMAP_* -> GL_LINEAR

#: Texels on the longer side below which a document's image with no
#: TextureProperties is sampled from its nearest texel.
SMALL_IMAGE = 16


def sampler_of(texture: Any, size: Optional[tuple[int, ...]] = None) -> "dict[str, str]":
    """The X3D boundary modes and filters an X3D texture is sampled with

    From its `textureProperties` node where there is one, else from
    `repeatS`/`repeatT` with the default filters, or with NEAREST_PIXEL for a
    document's image `size` (width, height, and a volume's depth) smaller
    than :data:`SMALL_IMAGE`. A 3D texture's or a cube map's also has
    `wrap_r`: its `repeatR`, or a cube map's faces clamped to their edges.
    """
    properties = getattr(texture, 'textureProperties', None)
    deep = hasattr(texture, 'repeatR') or isinstance(texture, x3d.X3DEnvironmentTextureNode)
    if properties:
        found = {
            'wrap_s': str(properties.boundaryModeS),
            'wrap_t': str(properties.boundaryModeT),
            'minification': str(properties.minificationFilter),
            'magnification': str(properties.magnificationFilter),
        }
        if deep:
            found['wrap_r'] = str(properties.boundaryModeR)
        return found
    from OpenGLContext.lighting import in_document  # noqa: PLC0415 lighting reads the scene classes
    small = size is not None and max(size) < SMALL_IMAGE and in_document(texture)
    filter_ = 'NEAREST_PIXEL' if small else 'DEFAULT'

    def wrap(name: str) -> str:
        return 'REPEAT' if getattr(texture, name, True) else 'CLAMP_TO_EDGE'
    found = {
        'wrap_s': wrap('repeatS'), 'wrap_t': wrap('repeatT'),
        'minification': filter_,
        'magnification': filter_,
    }
    if deep:
        # A cube map has no repeat fields, and its faces meet at their edges.
        found['wrap_r'] = wrap('repeatR') if hasattr(texture, 'repeatR') else 'CLAMP_TO_EDGE'
        if not hasattr(texture, 'repeatR'):
            found['wrap_s'] = found['wrap_t'] = 'CLAMP_TO_EDGE'
    return found


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
    """Set a sampler (as `sampler_of` gives it) on a GL texture object, with mipmaps

    The texture's `target` says what it is bound to: a 2D texture where it
    names none. A 3D texture's or a cube map's sampler also gives `wrap_r`.
    """
    from OpenGL import GL  # noqa: PLC0415 GL only when a texture is compiled
    target = getattr(texture, 'target', GL.GL_TEXTURE_2D)
    GL.glBindTexture(target, texture.texture)
    wraps = [(GL.GL_TEXTURE_WRAP_S, 'wrap_s'), (GL.GL_TEXTURE_WRAP_T, 'wrap_t')]
    if target != GL.GL_TEXTURE_2D:
        wraps.append((GL.GL_TEXTURE_WRAP_R, 'wrap_r'))
    for parameter, name in wraps:
        GL.glTexParameteri(target, parameter,
                           getattr(GL, WRAP_MODES.get(sampler.get(name, 'REPEAT'), 'GL_REPEAT')))
    minification = getattr(GL, MINIFICATION.get(sampler['minification'],
                                                 'GL_LINEAR_MIPMAP_LINEAR'))
    # A texture that brought its own mip levels (a Basis Universal file's,
    # perhaps block-compressed, which GL cannot generate from) keeps them; one
    # level is sampled without mipmaps.
    levels = getattr(texture, 'mip_levels', 0)
    if levels == 1:
        minification = _WITHOUT_MIPMAPS.get(minification, minification)
    elif not levels:
        try:
            GL.glGenerateMipmap(target)
        except GL.GLError:
            minification = GL.GL_LINEAR
    GL.glTexParameteri(target, GL.GL_TEXTURE_MIN_FILTER, minification)
    GL.glTexParameteri(target, GL.GL_TEXTURE_MAG_FILTER,
                       getattr(GL, MAGNIFICATION.get(sampler['magnification'], 'GL_LINEAR')))
