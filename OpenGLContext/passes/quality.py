"""How finely primitives are tessellated and textures filtered -- no GL

X_ITE's ``PrimitiveQuality`` and ``TextureQuality`` options, and X3D's browser
options of those names (19775-1, Table 9.2), as
``ContextDefinition.primitiveQuality`` (``OPENGLCONTEXT_PRIMITIVE_QUALITY``)
and ``ContextDefinition.textureQuality`` (``OPENGLCONTEXT_TEXTURE_QUALITY``):
``auto``, ``low``, ``medium`` or ``high``.

Primitive quality is the number of sides of a Cone and a Cylinder and the
sides and rings of a Sphere, X_ITE's counts (:data:`PRIMITIVES`). ``auto`` is
``medium`` for a node of a VRML97 or X3D document, X_ITE's default, and the
engine's own tessellation (the Sphere's ``phi``, 32 sides for the others)
for a node built in code. Distance level of detail
(:mod:`OpenGLContext.scenegraph.tessellationlod`) steps down from it.

Texture quality is the filters a texture is sampled with where it names
none: no ``TextureProperties``, or one whose filters are ``DEFAULT``
(:data:`TEXTURE_FILTERS`). ``auto`` is ``medium`` for a document's texture,
X_ITE's default, and ``high`` for any other. ``FASTEST`` and ``NICEST`` are
X_ITE's low and high filters whatever the quality.

The render pass says which choices a frame draws with (:func:`use`), as it
does the lighting rules; a mesh or texture made in that frame reads them.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ['QUALITIES', 'CHOICES', 'LABELS', 'PRIMITIVES', 'TEXTURE_FILTERS',
           'use', 'chosen', 'resolve', 'primitive_quality', 'texture_quality',
           'cone_sides', 'sphere_dimensions', 'texture_filters',
           'default_primitive_quality', 'default_texture_quality']

#: The qualities, lowest first.
QUALITIES: tuple[str, ...] = ('low', 'medium', 'high')
#: What the two fields accept.
CHOICES: tuple[str, ...] = ('auto',) + QUALITIES
#: What a settings screen shows for each of those.
LABELS: tuple[str, ...] = ('By the scene', 'Low', 'Medium', 'High')

#: Per quality: the sides of a Cone and a Cylinder, and a Sphere's sides and
#: rings (X_ITE 16.4.3's counts).
PRIMITIVES: dict[str, tuple[int, int, int]] = {
    'low': (16, 20, 8),
    'medium': (20, 32, 14),
    'high': (32, 64, 30),
}

#: Per quality: the minification and magnification filters, in X3D's names,
#: for a texture that names none (X_ITE 16.4.3's default TextureProperties).
TEXTURE_FILTERS: dict[str, tuple[str, str]] = {
    'low': ('NEAREST_PIXEL_NEAREST_MIPMAP', 'NEAREST_PIXEL'),
    'medium': ('AVG_PIXEL_NEAREST_MIPMAP', 'AVG_PIXEL'),
    'high': ('AVG_PIXEL_AVG_MIPMAP', 'AVG_PIXEL'),
}

#: X3D's FASTEST and NICEST filters, as X_ITE reads them.
NAMED_FILTERS: dict[str, dict[str, str]] = {
    'minification': {'FASTEST': 'NEAREST_PIXEL_NEAREST_MIPMAP',
                     'NICEST': 'AVG_PIXEL_AVG_MIPMAP'},
    'magnification': {'FASTEST': 'NEAREST_PIXEL', 'NICEST': 'AVG_PIXEL'},
}

_current = {'primitive': 'auto', 'texture': 'auto'}


def default_primitive_quality() -> str:
    """``OPENGLCONTEXT_PRIMITIVE_QUALITY``, one of :data:`CHOICES`, else ``auto``"""
    from OpenGLContext import renderoptions
    return renderoptions.env_choice_once('OPENGLCONTEXT_PRIMITIVE_QUALITY', CHOICES, {}, 'auto')


def default_texture_quality() -> str:
    """``OPENGLCONTEXT_TEXTURE_QUALITY``, one of :data:`CHOICES`, else ``auto``"""
    from OpenGLContext import renderoptions
    return renderoptions.env_choice_once('OPENGLCONTEXT_TEXTURE_QUALITY', CHOICES, {}, 'auto')


def chosen(source: Any) -> tuple[str, str]:
    """(primitive, texture) choices ``source``'s definition makes"""
    from OpenGLContext import renderoptions
    return (renderoptions.choice(source, 'primitiveQuality', default_primitive_quality()),
            renderoptions.choice(source, 'textureQuality', default_texture_quality()))


def resolve(choice: str) -> str:
    """``choice`` checked and lower-cased: one of :data:`CHOICES`"""
    choice = str(choice).lower()
    if choice not in CHOICES:
        raise ValueError('a quality is one of %s, not %r' % (CHOICES, choice))
    return choice


def use(primitive: str, texture: str) -> None:
    """Draw from now on with these choices (:data:`CHOICES`)"""
    _current['primitive'] = resolve(primitive)
    _current['texture'] = resolve(texture)


def primitive_quality(document: bool) -> Optional[str]:
    """The primitive quality in use for a node, or None for the engine's tessellation"""
    choice = _current['primitive']
    if choice == 'auto':
        return 'medium' if document else None
    return choice


def texture_quality(document: bool) -> str:
    """The texture quality in use for a texture"""
    choice = _current['texture']
    if choice == 'auto':
        return 'medium' if document else 'high'
    return choice


def cone_sides(quality: str) -> int:
    """Sides of a Cone or a Cylinder at ``quality``"""
    return PRIMITIVES[quality][0]


def sphere_dimensions(quality: str) -> tuple[int, int]:
    """(sides, rings) of a Sphere at ``quality``"""
    _cone, sides, rings = PRIMITIVES[quality]
    return sides, rings


def texture_filters(minification: str, magnification: str, quality: str) -> tuple[str, str]:
    """The X3D filters a texture asking for these is sampled with at ``quality``

    ``DEFAULT`` takes the quality's filter, ``FASTEST`` and ``NICEST`` X_ITE's
    readings of them; any other name is kept.
    """
    default_min, default_mag = TEXTURE_FILTERS[quality]

    def named(value: str, kind: str, default: str) -> str:
        value = str(value)
        if value == 'DEFAULT':
            return default
        return NAMED_FILTERS[kind].get(value, value)
    return (named(minification, 'minification', default_min),
            named(magnification, 'magnification', default_mag))
