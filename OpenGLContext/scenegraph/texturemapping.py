"""Which texture coordinates each material channel reads, and through which transform

X3D names a texture's coordinates with a mapping label. A material's
`...TextureMapping` field gives each channel's label; the geometry says which
of its coordinate sets the label names (:func:`coordinate_set`), and the
appearance's `textureTransform` holds the transform with that label
(:func:`transform_for`). An empty label is the first coordinate set, and a
single transform whose `mapping` is empty applies to every channel, as in
VRML97.

:func:`texture_mapping` reduces that to what the PBR shader reads for one
draw: for each channel a coordinate set and a transform slot, packed into
`codes`, and up to :data:`MAX_TRANSFORMS` distinct transforms as 2x3
matrices. It is kept in vrml's cache against the appearance and the fields it
was read from. No GL.
"""
import logging
import re
import weakref
from math import cos, sin
from typing import Any, NamedTuple, Optional

import numpy as np

from vrml import cache, node, protofunctions
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.physicalmaterial import ChannelMaterial, pbr_material

log = logging.getLogger(__name__)

#: The channels in the order the shader numbers them (`CH_*` in pbr.frag): the
#: core maps, then the extension maps in their texture units' order.
CHANNELS = (
    'baseColor', 'metallicRoughness', 'normal', 'occlusion', 'emissive', 'lightmap',
    'transmission', 'iridescenceThickness', 'clearcoat', 'clearcoatRoughness',
    'thickness', 'anisotropy', 'specular', 'specularColor', 'sheenColor',
    'sheenRoughness', 'iridescence', 'clearcoatNormal', 'diffuseTransmissionColor',
    'diffuseTransmission',
)

#: How many distinct transforms one draw's channels can use.
MAX_TRANSFORMS = 4
#: How many coordinate sets the shader reads (TEXCOORD_0 and TEXCOORD_1).
MAX_SETS = 2
#: Channels packed into one code word, five bits each: two for the set, three
#: for the transform slot (0 for none).
PER_WORD = 6
#: Code words for every channel.
WORDS = (len(CHANNELS) + PER_WORD - 1) // PER_WORD

_TEXCOORD = re.compile(r'^TEXCOORD_(\d+)(?::.*)?$')
_IDENTITY = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], 'f')
_KEY = 'texture-mapping'
_reported: "set[str]" = set()


def _report(message: str) -> None:
    if message not in _reported:
        _reported.add(message)
        log.warning(message)


class TextureMapping(NamedTuple):
    """One draw's texture coordinates: what the PBR shader's `uvFor` reads"""

    #: Each channel's coordinate set and transform slot, packed.
    codes: "tuple[int, ...]"
    #: The transforms, `MAX_TRANSFORMS` 2x3 matrices, identity where unused.
    transforms: np.ndarray

    @property
    def key(self) -> tuple:
        """A value equal for two mappings that draw alike"""
        return (self.codes, self.transforms.tobytes())


#: A draw with no texture coordinates to choose: every channel reads the first
#: set, untransformed.
IDENTITY = TextureMapping((0,) * WORDS, np.repeat(_IDENTITY[None], MAX_TRANSFORMS, axis=0))


def coordinate_set(geometry: Any, label: str) -> int:
    """The coordinate set of `geometry` that a mapping label names

    A geometry with a `textureCoordinateSet(label)` method answers for
    itself. Otherwise an empty label is set 0, and `TEXCOORD_n`, with or
    without a `:suffix`, is set n. Any other label is reported once and read
    as set 0.
    """
    named = getattr(geometry, 'textureCoordinateSet', None)
    if callable(named):
        return int(named(label))
    if not label:
        return 0
    match = _TEXCOORD.match(label)
    if match is None:
        _report('Texture mapping %r names no coordinate set here; read as TEXCOORD_0' % label)
        return 0
    return int(match.group(1))


def transform_for(appearance: Any, label: str) -> Any:
    """The texture transform node of `appearance` that applies to `label`, or None

    A `MultiTextureTransform`'s entry whose `mapping` is the label, or a
    single transform whose `mapping` is the label or empty.
    """
    transform = getattr(appearance, 'textureTransform', None)
    if not transform:
        return None
    if isinstance(transform, x3d.MultiTextureTransform):
        for entry in transform.textureTransform:
            if str(getattr(entry, 'mapping', '')) == label:
                return entry
        return None
    return transform if str(getattr(transform, 'mapping', '')) in ('', label) else None


def transform_matrix(transform: Any) -> np.ndarray:
    """A texture transform node as a 2x3 matrix applied to a column `(s, t, 1)`

    `TextureTransformMatrix3D`: its matrix's rows for s and t, with the
    translation in the last column; `TextureTransform`: X3D's composition of
    its center, rotation, scale and translation. Any other node is reported
    once and read as no transform.
    """
    if transform is None:
        return _IDENTITY.copy()
    if isinstance(transform, x3d.TextureTransformMatrix3D):
        matrix = np.asarray(transform.matrix, 'f').reshape(4, 4)
        return np.array([[matrix[0, 0], matrix[0, 1], matrix[0, 3]],
                         [matrix[1, 0], matrix[1, 1], matrix[1, 3]]], 'f')
    if isinstance(transform, x3d.TextureTransform):
        return texture_transform_matrix(transform)[:2].astype('f')
    _report('Texture transform %s is drawn untransformed'
            % protofunctions.protoName(transform))
    return _IDENTITY.copy()


def _translate(tx: float, ty: float) -> np.ndarray:
    m = np.eye(3, dtype='f')
    m[0, 2] = tx
    m[1, 2] = ty
    return m


def _scale(sx: float, sy: float) -> np.ndarray:
    m = np.eye(3, dtype='f')
    m[0, 0] = sx
    m[1, 1] = sy
    return m


def _rotate(angle: float) -> np.ndarray:
    c, s = cos(angle), sin(angle)
    m = np.eye(3, dtype='f')
    m[0, 0], m[0, 1] = c, -s
    m[1, 0], m[1, 1] = s, c
    return m


def texture_transform_matrix(transform_node: Optional[Any]) -> np.ndarray:
    """A TextureTransform node as a 3x3 homogeneous matrix; None is the identity

    Composed as VRML97 and X3D give it: translate by the center, rotate,
    scale, translate back, then translate.
    """
    if transform_node is None:
        return np.eye(3, dtype='f')
    tx, ty = transform_node.translation
    cx, cy = transform_node.center
    angle = transform_node.rotation
    sx, sy = transform_node.scale
    m = np.eye(3, dtype='f')
    if cx != 0 or cy != 0:
        m = m @ _translate(cx, cy)
    if angle != 0:
        m = m @ _rotate(angle)
    if sx != 1 or sy != 1:
        m = m @ _scale(sx, sy)
    if cx != 0 or cy != 0:
        m = m @ _translate(-cx, -cy)
    if tx != 0 or ty != 0:
        m = m @ _translate(tx, ty)
    return m


def channel_labels(material: Any) -> "dict[str, str]":
    """Each textured channel of a material and its mapping label"""
    textures = getattr(material, 'textures', None) or {}
    if not isinstance(material, ChannelMaterial):
        return {channel: '' for channel in textures}
    return {channel: str(getattr(material, material.CHANNELS[channel] + 'Mapping', ''))
            for channel in textures}


def texture_mapping(appearance: Any, geometry: Any) -> TextureMapping:
    """The texture coordinates and transforms a draw of `appearance` on `geometry` reads

    Kept in vrml's cache against the appearance until a field it was read
    from is set: the appearance's material, texture and transform, the
    material's fields, and the transform nodes' fields. An appearance that is
    not a node has no fields to watch, and is read afresh each time.
    """
    if not appearance:
        return IDENTITY
    if not isinstance(appearance, node.Node):
        return _compute(appearance, geometry)
    holder = cache.CACHE.getHolder(appearance, _KEY)
    if holder is None or holder.data is None:
        holder = cache.CACHE.holder(appearance, weakref.WeakKeyDictionary(), _KEY)
        _depend(holder, appearance)
    by_geometry = holder.data
    found = by_geometry.get(geometry) if geometry is not None else None
    if found is None:
        found = _compute(appearance, geometry)
        if geometry is not None:
            by_geometry[geometry] = found
    return found


def _depend(holder: Any, appearance: Any) -> None:
    """Make `holder` clear when any field the mapping is read from is set"""
    for name in ('material', 'texture', 'textureTransform'):
        holder.depend(appearance, name)
    material = getattr(appearance, 'material', None)
    transform = getattr(appearance, 'textureTransform', None)
    sources = [material, transform]
    if isinstance(transform, x3d.MultiTextureTransform):
        sources.extend(transform.textureTransform)
    for source in sources:
        if source:
            for declared in protofunctions.getFields(source):
                if not declared.name.startswith(' '):
                    holder.depend(source, declared)


def _compute(appearance: Any, geometry: Any) -> TextureMapping:
    """The mapping, worked out from the nodes as they stand"""
    material = pbr_material(appearance)
    codes = [0] * WORDS
    transforms = [_IDENTITY]
    slots: "dict[bytes, int]" = {}
    for channel, label in channel_labels(material).items():
        index = CHANNELS.index(channel)
        chosen = coordinate_set(geometry, label)
        if chosen >= MAX_SETS:
            _report('Texture mapping %r names coordinate set %d; the renderer reads %d'
                    % (label, chosen, MAX_SETS))
            chosen = 0
        slot = 0
        transform = transform_for(appearance, label)
        if transform is not None:
            matrix = transform_matrix(transform)
            if not np.allclose(matrix, _IDENTITY):
                slot = slots.get(matrix.tobytes(), 0)
                if not slot:
                    if len(transforms) > MAX_TRANSFORMS:
                        _report('A draw uses more than %d texture transforms; '
                                'the rest are drawn untransformed' % MAX_TRANSFORMS)
                    else:
                        slot = slots[matrix.tobytes()] = len(transforms)
                        transforms.append(matrix)
        codes[index // PER_WORD] |= (chosen | (slot << 2)) << (5 * (index % PER_WORD))
    table = np.repeat(_IDENTITY[None], MAX_TRANSFORMS, axis=0)
    for slot, matrix in enumerate(transforms[1:]):
        table[slot] = matrix
    return TextureMapping(tuple(codes), table)
