"""The stage chain a MultiTexture, a cube map or a 3D texture is drawn as -- no GL

X3D's ``MultiTexture`` (ISO/IEC 19775-1, 18.4.3) combines its textures in
order. The colour so far starts as the material's diffuse colour (a
``PhysicalMaterial``'s base colour, an ``UnlitMaterial``'s emissive colour,
or the ``Color`` node's where the geometry has one). For each texture, the
first argument is the texture's colour, or the ``source`` named for it
(``DIFFUSE`` the material's diffuse colour, ``SPECULAR`` its specular colour,
``FACTOR`` the MultiTexture's ``color`` and ``alpha``), after its
``function`` (``COMPLEMENT`` takes it from one, ``ALPHA_REPLICATE`` gives it
the second argument's alpha); the second is the colour so far; and its
``mode`` combines them into the next colour so far. A mode may name a second
operation for the alpha, after a comma (``"MODULATE,REPLACE"``); the names
X3D 3 wrote without underscores (``MODULATEALPHA_ADDCOLOR``,
``BLENDDIFFUSEALPHA``) are read as the names with them. The last colour so
far is the surface's diffuse (base, emissive) colour.

A cube map (``X3DEnvironmentTextureNode``) or a 3D texture
(``X3DTexture3DNode``) in an appearance's ``texture`` field is the same chain
of one texture that modulates. An ordinary 2D texture there is not a chain:
it is the material's base colour map, as it has always been.

:func:`texture_layers` reads an appearance and the geometry drawn with it
into a :class:`LayerTable` the shaders read (``shaders/_layers_inc.glsl``):

- Layer i reads the geometry's texture coordinate node at position i of its
  ``MultiTextureCoordinate``, or the last one where there are fewer, and the
  appearance's ``MultiTextureTransform`` entry at position i likewise; a
  single coordinate node or transform serves every layer.
- A 2D texture reads coordinate set 0 or 1 (a set past them is reported and
  read as set 0), a ``TextureCoordinateGenerator``'s coordinates, made per
  fragment in its mode, or a ``TextureCoordinate3D``/``4D``'s s and t.
- A 3D texture reads the geometry's ``TextureCoordinate3D`` or ``4D`` (its
  first: a geometry carries one), a generator's three coordinates, or, where
  the geometry has no coordinates for it, its position across the geometry's
  bounding box: s along x, t along y and r along z, 0 to 1.
- A cube map reads the world-space reflection of the view about the
  surface, whatever coordinates the geometry gives it, so it is an
  environment the surface reflects.

At most :data:`MAX_LAYERS` textures are combined; the rest are reported once
and left out. The table is kept in vrml's cache against the appearance and
every field it was read from (:func:`texture_layers`).
"""
from __future__ import annotations

import logging
import math
import weakref
from typing import Any, NamedTuple, Optional

import numpy as np
from vrml import cache, node, protofunctions
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import texgen
from OpenGLContext.scenegraph.physicalmaterial import pbr_material
from OpenGLContext.scenegraph.texturemapping import MAX_SETS, texture_transform_matrix

log = logging.getLogger(__name__)

__all__ = [
    'COORD_BOX', 'COORD_GENERATED', 'COORD_REFLECTION', 'COORD_SET', 'COORD_VOLUME',
    'FUNCTIONS', 'KIND_2D', 'KIND_3D', 'KIND_CUBE', 'Layer', 'LayerTable', 'MAX_LAYERS',
    'MODES', 'SOURCES', 'compute_layers', 'drawn_singly', 'is_layered', 'layer_kind', 'parse_function',
    'parse_mode', 'parse_source', 'texture_layers', 'transform_matrix',
]

#: How many textures one draw combines (the shaders' MAX_TEXTURE_LAYERS).
MAX_LAYERS = 4

#: The shaders' number for each mode (``LAYER_MODE_*`` in _layers_inc.glsl).
MODES: dict[str, int] = {
    'MODULATE': 1, 'REPLACE': 2, 'MODULATE_2X': 3, 'MODULATE_4X': 4, 'ADD': 5,
    'ADD_SIGNED': 6, 'ADD_SIGNED_2X': 7, 'ADD_SMOOTH': 8, 'SUBTRACT': 9,
    'BLEND_DIFFUSE_ALPHA': 10, 'BLEND_TEXTURE_ALPHA': 11, 'BLEND_FACTOR_ALPHA': 12,
    'BLEND_CURRENT_ALPHA': 13, 'MODULATE_ALPHA_ADD_COLOR': 14,
    'MODULATE_INV_ALPHA_ADD_COLOR': 15, 'MODULATE_INV_COLOR_ADD_ALPHA': 16,
    'DOT_PRODUCT_3': 17, 'SELECT_ARG1': 18, 'SELECT_ARG2': 19, 'OFF': 20,
}
#: The first argument in place of the texture's colour; 0 is the texture.
SOURCES: dict[str, int] = {'DIFFUSE': 1, 'SPECULAR': 2, 'FACTOR': 3}
#: What is done to the first argument; 0 is nothing.
FUNCTIONS: dict[str, int] = {'COMPLEMENT': 1, 'ALPHA_REPLICATE': 2}

#: The sampler a layer is read through.
KIND_2D = 1
KIND_CUBE = 2
KIND_3D = 3

#: Where a layer's coordinates come from: a 2D coordinate set, a generator,
#: the geometry's 3D coordinate set, the geometry's bounding box, or the
#: reflected view.
COORD_SET = 0
COORD_GENERATED = 1
COORD_VOLUME = 2
COORD_BOX = 3
COORD_REFLECTION = 4

#: Each name with its underscores taken out, to the name: X3D 3 wrote some
#: without them.
_BY_LETTERS = {name.replace('_', ''): name for name in MODES}
_KEY = 'texture-layers'
_IDENTITY = np.eye(4, dtype=np.float32)[:3]
_reported: set[str] = set()


def _report(message: str) -> None:
    if message not in _reported:
        _reported.add(message)
        log.warning(message)


def parse_mode(text: str) -> tuple[int, int]:
    """The colour and alpha operations a ``mode`` string names

    One name is both; ``"COLOUR,ALPHA"`` names each. A name that is not a
    mode is reported once and read as ``MODULATE``.
    """
    names = [part.strip() for part in str(text).split(',')]
    if len(names) < 2:
        names.append(names[0])

    def one(name: str) -> int:
        found = _BY_LETTERS.get(name.upper().replace('_', ''))
        if found is None:
            if name:
                _report('MultiTexture mode %r is not a mode; drawn as MODULATE' % (name,))
            found = 'MODULATE'
        return MODES[found]
    return one(names[0]), one(names[1])


def parse_source(text: str) -> int:
    """The number of a ``source`` string; 0 (the texture) for an empty or unknown one"""
    name = str(text).strip().upper()
    if name and name not in SOURCES:
        _report('MultiTexture source %r is not a source; the texture is read' % (text,))
    return SOURCES.get(name, 0)


def parse_function(text: str) -> int:
    """The number of a ``function`` string; 0 (none) for an empty or unknown one"""
    name = str(text).strip().upper().replace('_', '')
    for known, number in FUNCTIONS.items():
        if known.replace('_', '') == name:
            return number
    if name:
        _report('MultiTexture function %r is not a function; none is applied' % (text,))
    return 0


def layer_kind(texture: Any) -> int:
    """The sampler a texture node is read through: 2D, cube or 3D"""
    if isinstance(texture, x3d.X3DEnvironmentTextureNode):
        return KIND_CUBE
    if isinstance(texture, x3d.X3DTexture3DNode):
        return KIND_3D
    return KIND_2D


def is_layered(texture: Any) -> bool:
    """Whether a texture node is drawn as a stage chain rather than a base colour map"""
    return isinstance(texture, (x3d.MultiTexture, x3d.X3DEnvironmentTextureNode,
                                x3d.X3DTexture3DNode))


def drawn_singly(texture: Any) -> bool:
    """Whether a shape wearing ``texture`` is drawn by itself, never batched

    A stage chain reads its own geometry's coordinates, and a rendered
    texture is drawn from the shape that wears it.
    """
    return is_layered(texture) or isinstance(texture, x3d.RenderedTexture)


class Layer(NamedTuple):
    """One texture of the chain, and how it is read and combined"""

    texture: Any
    kind: int
    coordinate: int
    #: The 2D coordinate set read, for :data:`COORD_SET`.
    set: int
    #: The generator's mode number (``texgen.MODES``), for :data:`COORD_GENERATED`.
    generator: int
    parameters: tuple[float, ...]
    #: Applied to the coordinates ``(s, t, r, 1)``: three rows of four.
    transform: np.ndarray
    mode: int
    alpha_mode: int
    source: int
    function: int

    @property
    def key(self) -> tuple:
        """A value equal for two layers read and combined alike"""
        return (self.kind, self.coordinate, self.set, self.generator, self.parameters,
                self.transform.tobytes(), self.mode, self.alpha_mode, self.source,
                self.function)


class LayerTable(NamedTuple):
    """The layers one draw combines, and the MultiTexture's colour and alpha"""

    layers: tuple[Layer, ...]
    #: ``FACTOR``: the MultiTexture's ``color`` and ``alpha``.
    factor: tuple[float, float, float, float]

    @property
    def key(self) -> tuple:
        """A value equal for two tables drawn alike from the same textures"""
        return (tuple(layer.key for layer in self.layers), self.factor)

    @property
    def needs_box(self) -> bool:
        """Whether a layer reads the geometry's bounding box"""
        return any(layer.coordinate == COORD_BOX for layer in self.layers)


def _translate(offset: Any) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, 3] = offset
    return matrix


def _scale(factors: Any) -> np.ndarray:
    return np.diag(list(factors) + [1.0])


def _rotate(axis_angle: Any) -> np.ndarray:
    x, y, z, angle = (float(value) for value in axis_angle)
    length = math.sqrt(x * x + y * y + z * z)
    if not length or not angle:
        return np.eye(4)
    x, y, z = x / length, y / length, z / length
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    matrix = np.eye(4)
    matrix[:3, :3] = [
        [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ]
    return matrix


def transform_matrix(transform: Any) -> np.ndarray:
    """A texture transform node as three rows applied to ``(s, t, r, 1)``

    ``TextureTransform`` as its 2D composition with r untouched;
    ``TextureTransform3D`` the same composition in three dimensions (the
    centre, the rotation, the scale, the centre back, then the translation);
    ``TextureTransformMatrix3D`` its matrix, read as
    :mod:`~OpenGLContext.scenegraph.texturemapping` reads it. Any other node,
    and None, is no transform.
    """
    if transform is None:
        return _IDENTITY.copy()
    if isinstance(transform, x3d.TextureTransformMatrix3D):
        return np.asarray(transform.matrix, np.float32).reshape(4, 4)[:3].copy()
    if isinstance(transform, x3d.TextureTransform3D):
        centre = np.asarray(transform.center, np.float64)
        matrix = (_translate(centre) @ _rotate(transform.rotation) @ _scale(transform.scale)
                  @ _translate(-centre) @ _translate(transform.translation))
        return matrix[:3].astype(np.float32)
    if isinstance(transform, x3d.TextureTransform):
        flat = texture_transform_matrix(transform)
        found = _IDENTITY.copy()
        found[:2, :2] = flat[:2, :2]
        found[:2, 3] = flat[:2, 2]
        return found
    return _IDENTITY.copy()


def coordinate_nodes(geometry: Any) -> list[Any]:
    """A geometry's texture coordinate nodes, in order"""
    found = getattr(geometry, 'texCoord', None)
    if not found:
        return []
    if isinstance(found, x3d.MultiTextureCoordinate):
        return [entry for entry in found.texCoord if entry]
    return [found]


def _transform_nodes(appearance: Any) -> list[Any]:
    found = getattr(appearance, 'textureTransform', None)
    if not found:
        return []
    if isinstance(found, x3d.MultiTextureTransform):
        return [entry for entry in found.textureTransform if entry]
    return [found]


def _at(entries: list[Any], index: int) -> Any:
    return entries[min(index, len(entries) - 1)] if entries else None


_VOLUME_COORDINATES = (x3d.TextureCoordinate3D, x3d.TextureCoordinate4D)


def _coordinates(kind: int, entries: list[Any], index: int,
                 geometry: Any) -> tuple[int, int, int, tuple[float, ...]]:
    """(coordinate, set, generator, parameters) for layer ``index``"""
    none = (0.0,) * texgen.PARAMETERS
    if kind == KIND_CUBE:
        return COORD_REFLECTION, 0, 0, none
    entry = _at(entries, index)
    generated = texgen.texgen_of(entry)
    if generated is not None:
        return COORD_GENERATED, 0, generated.mode, generated.parameters
    if isinstance(entry, _VOLUME_COORDINATES):
        if callable(getattr(geometry, 'volumeCoordinates', None)):
            return COORD_VOLUME, 0, 0, none
        _report('%s does not carry 3D texture coordinates; its 3D textures are read '
                'across its bounds' % (protofunctions.protoName(geometry),))
        return (COORD_BOX if kind == KIND_3D else COORD_SET), 0, 0, none
    if entry is None and kind == KIND_3D:
        return COORD_BOX, 0, 0, none
    number = min(index, len(entries) - 1) if entries else 0
    if number >= MAX_SETS:
        _report('A MultiTexture layer reads coordinate set %d; the renderer reads %d, '
                'and reads the first in its place' % (number, MAX_SETS))
        number = 0
    return COORD_SET, number, 0, none


def base_texture(appearance: Any, back: bool = False) -> Any:
    """The texture node an appearance's base colour comes from, or None"""
    material = pbr_material(appearance, back)
    textures = getattr(material, 'textures', None) or {}
    return textures.get('baseColor')


def compute_layers(appearance: Any, geometry: Any, back: bool = False) -> Optional[LayerTable]:
    """The layers an appearance draws on a geometry, worked out now; None for no chain"""
    if not appearance:
        return None
    texture = base_texture(appearance, back)
    if not is_layered(texture):
        return None
    if isinstance(texture, x3d.MultiTexture):
        textures = list(texture.texture)
        modes, sources, functions = list(texture.mode), list(texture.source), list(texture.function)
        factor = tuple(float(value) for value in texture.color)[:3] + (float(texture.alpha),)
    else:
        textures, modes, sources, functions = [texture], [], [], []
        factor = (1.0, 1.0, 1.0, 1.0)
    entries = coordinate_nodes(geometry)
    transforms = _transform_nodes(appearance)
    layers = []
    for index, child in enumerate(textures):
        if not child:
            continue
        if isinstance(child, x3d.MultiTexture):
            _report('A MultiTexture inside a MultiTexture is left out')
            continue
        if len(layers) == MAX_LAYERS:
            _report('A MultiTexture combines more than %d layers; the rest are left out'
                    % (MAX_LAYERS,))
            break
        kind = layer_kind(child)
        coordinate, number, generator, parameters = _coordinates(kind, entries, index, geometry)
        mode, alpha_mode = parse_mode(modes[index]) if index < len(modes) else (
            MODES['MODULATE'], MODES['MODULATE'])
        layers.append(Layer(
            child, kind, coordinate, number, generator, tuple(parameters),
            transform_matrix(_at(transforms, index)), mode, alpha_mode,
            parse_source(sources[index]) if index < len(sources) else 0,
            parse_function(functions[index]) if index < len(functions) else 0))
    return LayerTable(tuple(layers), (factor[0], factor[1], factor[2], factor[3]))


def texture_layers(appearance: Any, geometry: Any, back: bool = False) -> Optional[LayerTable]:
    """The layers an appearance draws on a geometry; None where its base is no chain

    Kept in vrml's cache against the appearance until a field it was read
    from is set: the appearance's material, texture and transforms, the
    material's fields, the MultiTexture's and the transforms' fields, and
    the geometry's texture coordinate nodes and their fields.
    """
    if not appearance:
        return None
    if not isinstance(appearance, node.Node):
        return compute_layers(appearance, geometry, back)
    key = _KEY + ('-back' if back else '')
    holder = cache.CACHE.getHolder(appearance, key)
    if holder is None or holder.data is None:
        holder = cache.CACHE.holder(appearance, weakref.WeakKeyDictionary(), key)
        _depend(holder, appearance)
    by_geometry = holder.data
    marker = _NO_GEOMETRY if geometry is None else geometry
    try:
        found = by_geometry.get(marker, _MISSING)
    except TypeError:
        return compute_layers(appearance, geometry, back)
    if found is _MISSING:
        found = compute_layers(appearance, geometry, back)
        if geometry is not None:
            _depend_geometry(holder, geometry)
        by_geometry[marker] = found
    return found


class _Marker:
    """A key standing for no geometry in the weak table"""


_NO_GEOMETRY = _Marker()
_MISSING = object()


def _depend_fields(holder: Any, source: Any) -> None:
    for declared in protofunctions.getFields(source):
        if not declared.name.startswith(' '):
            holder.depend(source, declared)


def _depend(holder: Any, appearance: Any) -> None:
    """Make ``holder`` clear when a field the layers are read from is set"""
    for name in ('material', 'backMaterial', 'texture', 'textureTransform'):
        if hasattr(appearance, name):
            holder.depend(appearance, name)
    sources = [getattr(appearance, 'material', None), getattr(appearance, 'backMaterial', None),
               getattr(appearance, 'texture', None)]
    sources.extend(_transform_nodes(appearance))
    transform = getattr(appearance, 'textureTransform', None)
    if isinstance(transform, x3d.MultiTextureTransform):
        sources.append(transform)
    texture = getattr(appearance, 'texture', None)
    if isinstance(texture, x3d.MultiTexture):
        holder.depend(texture, 'texture')
    for source in sources:
        if source:
            _depend_fields(holder, source)


def _depend_geometry(holder: Any, geometry: Any) -> None:
    """Make ``holder`` clear when the geometry's coordinate nodes change"""
    if not isinstance(geometry, node.Node) or not hasattr(geometry, 'texCoord'):
        return
    holder.depend(geometry, 'texCoord')
    coordinates = geometry.texCoord
    if isinstance(coordinates, x3d.MultiTextureCoordinate):
        holder.depend(coordinates, 'texCoord')
    for entry in coordinate_nodes(geometry):
        _depend_fields(holder, entry)
