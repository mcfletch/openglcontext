"""KHR_gaussian_splatting: a point primitive read as a GaussianSplats node, and written back

A mesh primitive carrying the extension is a set of 3D Gaussians: ``POSITION``
and the extension's ``ROTATION``, ``SCALE``, ``OPACITY`` and spherical-harmonic
attributes, one value per splat. :func:`read_splats` makes the engine's
:class:`~OpenGLContext.scenegraph.gaussiansplats.GaussianSplats` of them, which
is X3D 4.1's node with the same fields; :func:`splat_primitive` writes one
back for :mod:`OpenGLContext.loaders.gltf.writer`.

The facts used are in ``specs/gaussian-splats.md``.

- The ``ellipse`` kernel is the one read. Another kernel, projection or
  sorting method is reported and drawn as the ellipse kernel, perspective
  projection and camera-distance order are.
- ``colorSpace`` is ``srgb_rec709_display`` or ``lin_rec709_display``, the
  node's ``SRGB_REC709_DISPLAY`` and ``LIN_REC709_DISPLAY``; another is
  reported and read as sRGB.
- A primitive missing a required attribute is reported and read as the point
  cloud the base specification describes, coloured by ``COLOR_0``.
- The primitive's material is not used for the splats.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from OpenGLContext.loaders.documentvalues import DocumentValues
from OpenGLContext.loaders.resolver import Resolver
from OpenGLContext.loaders.gltf.accessors import _read_floats, _read_normalized
from OpenGLContext.scenegraph import splatmath

if TYPE_CHECKING:
    import pygltflib
    from OpenGLContext.scenegraph.gaussiansplats import GaussianSplats

__all__ = ['ATTRIBUTE_PREFIX', 'COLOR_SPACES', 'EXTENSION', 'HARMONIC_ATTRIBUTES',
           'read_splats', 'splat_extension', 'splat_primitive']

EXTENSION = 'KHR_gaussian_splatting'
#: What the extension's attribute semantics begin with.
ATTRIBUTE_PREFIX = EXTENSION + ':'

#: The extension's colour spaces, by the node's ``colorSpace`` value.
COLOR_SPACES = {'SRGB_REC709_DISPLAY': 'srgb_rec709_display',
                'LIN_REC709_DISPLAY': 'lin_rec709_display'}

#: The coefficient attributes in the node's field order, degree 0 first.
HARMONIC_ATTRIBUTES = tuple(
    ATTRIBUTE_PREFIX + 'SH_DEGREE_%d_COEF_%d' % (degree, coefficient)
    for degree, count in enumerate(splatmath.SH_COEFFICIENTS)
    for coefficient in range(count))

#: The attributes a splat primitive must carry besides ``POSITION``.
REQUIRED = tuple(ATTRIBUTE_PREFIX + name for name in ('ROTATION', 'SCALE', 'OPACITY')) \
    + HARMONIC_ATTRIBUTES[:1]

#: The values the extension defines for each of its choices, the first the default.
_CHOICES = {'kernel': ('ellipse',), 'projection': ('perspective',),
            'sortingMethod': ('cameradistance',)}

#: The point mode a splat primitive is drawn in.
_POINTS = 0


def splat_extension(primitive: "pygltflib.Primitive") -> Optional[dict]:
    """A primitive's KHR_gaussian_splatting block, or None"""
    extensions = getattr(primitive, 'extensions', None) or {}
    found = extensions.get(EXTENSION) if isinstance(extensions, dict) else None
    return found if isinstance(found, dict) else None


def _attribute(primitive: "pygltflib.Primitive", name: str) -> Optional[int]:
    index = getattr(primitive.attributes, name, None)
    return int(index) if isinstance(index, int) and not isinstance(index, bool) else None


def read_splats(g: "pygltflib.GLTF2", primitive: "pygltflib.Primitive",
                resolver: Resolver,
                values: Optional[DocumentValues] = None) -> Optional["GaussianSplats"]:
    """The GaussianSplats node `primitive` describes; None where it is no splat primitive

    None also for a primitive missing a required attribute, which is reported
    through `values` and is then read as points.
    """
    from OpenGLContext.scenegraph.gaussiansplats import from_arrays  # noqa: PLC0415 the node imports GL
    block = splat_extension(primitive)
    if block is None:
        return None
    values = values if values is not None else DocumentValues()
    for key, options in _CHOICES.items():
        values.choice(block.get(key), options[0], '%s %s' % (EXTENSION, key), options)
    space = values.choice(block.get('colorSpace'), COLOR_SPACES['SRGB_REC709_DISPLAY'],
                          '%s colorSpace' % EXTENSION, COLOR_SPACES.values())
    mode = getattr(primitive, 'mode', None)
    if mode is not None and int(mode) != _POINTS:
        values.warn('%s primitive has mode %r; its splats are read as POINTS'
                    % (EXTENSION, mode))
    position = _attribute(primitive, 'POSITION')
    missing = [name for name in REQUIRED if _attribute(primitive, name) is None]
    if position is None or missing:
        values.warn('%s primitive has no %s; it is read as points'
                    % (EXTENSION, ', '.join(missing or ['POSITION'])))
        return None

    def read(name: str, reader: Callable[..., np.ndarray] = _read_normalized) -> np.ndarray:
        index = _attribute(primitive, name)
        assert index is not None
        return reader(g, index, resolver)

    harmonics = []
    for name in HARMONIC_ATTRIBUTES:
        if _attribute(primitive, name) is None:
            break
        harmonics.append(read(name))
    return from_arrays(
        positions=_read_floats(g, position, resolver),
        rotations=read(ATTRIBUTE_PREFIX + 'ROTATION'),
        scales=read(ATTRIBUTE_PREFIX + 'SCALE'),
        opacities=read(ATTRIBUTE_PREFIX + 'OPACITY'),
        harmonics=harmonics,
        color_space={value: key for key, value in COLOR_SPACES.items()}[space])


def splat_primitive(node: "GaussianSplats",
                    add_floats: Callable[[np.ndarray, str, bool], int]) -> tuple[dict, str]:
    """(primitive JSON, extension name) for `node`, its arrays given to `add_floats`

    `add_floats` takes an (N, k) float32 array, its accessor type and whether
    the accessor states its bounds, which ``POSITION``'s does, and returns
    the accessor's index. The splats written are the node's whole
    ones: positions with a scale, orientation and opacity each (an empty
    ``orientations`` is no turn, an empty ``opacities`` opaque), and the
    coefficients of the highest degree every splat has whole.
    """
    positions = np.asarray(node.positions, '<f4').reshape(-1, 3)
    count = len(positions)
    if not count:
        raise ValueError('a KHR_gaussian_splatting primitive needs at least one splat')
    columns: list[tuple[str, Any, Any, int]] = [
        ('ROTATION', node.orientations, (0.0, 0.0, 0.0, 1.0), 4),
        ('SCALE', node.scales, None, 3),
        ('OPACITY', node.opacities, 1.0, 1)]
    attributes = {'POSITION': add_floats(positions, 'VEC3', True)}
    for name, source, default, width in columns:
        array = np.asarray(source, '<f4').reshape(-1, width)
        if not len(array) and default is not None:
            array = np.tile(np.asarray(default, '<f4'), (count, 1))
        if len(array) < count:
            raise ValueError('GaussianSplats %s has %d values for %d positions'
                             % (name.lower(), len(array), count))
        array = array[:count]
        attributes[ATTRIBUTE_PREFIX + name] = add_floats(
            array.ravel() if width == 1 else array,
            'SCALAR' if width == 1 else 'VEC%d' % width, False)
    from OpenGLContext.scenegraph.gaussiansplats import HARMONIC_FIELDS  # noqa: PLC0415 the node imports GL
    coefficients = [np.asarray(getattr(node, name), '<f4').reshape(-1, 3)
                    for name in HARMONIC_FIELDS]
    degree = splatmath.complete_degree([len(rows) for rows in coefficients], count)
    if degree < 0:
        raise ValueError('GaussianSplats needs sphericalHarmonicsDegree0Coef0 for each '
                         'of its %d positions' % count)
    for name, rows in zip(HARMONIC_ATTRIBUTES[:(degree + 1) ** 2], coefficients):
        attributes[name] = add_floats(rows[:count], 'VEC3', False)
    block = {'kernel': 'ellipse',
             'colorSpace': COLOR_SPACES.get(str(node.colorSpace), 'srgb_rec709_display')}
    return {'attributes': attributes, 'mode': _POINTS,
            'extensions': {EXTENSION: block}}, EXTENSION
