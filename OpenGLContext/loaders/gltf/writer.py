"""glTF 2.0 writer: scenegraph meshes and PBR materials out as a ``.glb``.

The counterpart to :mod:`OpenGLContext.loaders.gltf.loader`. It takes the same
objects the loader produces -- :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh`
geometry and :class:`~OpenGLContext.scenegraph.physicalmaterial.PhysicalMaterial` materials
-- and writes a binary glTF document, so anything the engine can render it can
also export, and a mesh written is the mesh that loads back.

The common case is one call::

    from OpenGLContext.loaders.gltf.writer import write_glb
    data = write_glb(mesh, path='tile.glb')

``write_glb`` accepts a mesh, a list of meshes, a :class:`SceneNode`, or a list of
nodes, and returns the bytes it wrote. :class:`SceneNode` adds a name, a local
transform, children, and -- through :class:`InstanceSet` -- the
``EXT_mesh_gpu_instancing`` attributes that let thousands of copies of one mesh
ride in a single document. :class:`GLTFWriter` is underneath for callers that
want to interleave building and inspect indices as they go.

What is written is the subset the engine's PBR path reads: mesh primitives with
position/normal/UV/tangent/colour attributes, metallic-roughness materials with
their five texture channels and the ``KHR_materials_*`` factors, embedded PNG
images with their samplers, a node hierarchy, GPU instancing, and Gaussian
splats as ``KHR_gaussian_splatting`` primitives. Skinning,
animation and morph targets are not written; a document that needs them is
authored elsewhere.

Sources: the glTF 2.0 specification (§3 the asset, §4 the binary container,
§5 concepts) and the Khronos extension registry.
"""
from __future__ import annotations

import io
import json
import os
import struct
from dataclasses import dataclass, field as dataclass_field
from collections.abc import Iterable, Sequence
from typing import Any, Generic, Optional, TypeVar, Union

import numpy as np

from OpenGLContext import __version__ as _engine_version
from OpenGLContext.loaders.documentvalues import bounded
from OpenGLContext.loaders.gltf import hooks as _hooks
from OpenGLContext.loaders.gltf.splats import splat_primitive
from OpenGLContext.loaders.gltf import variants as variantsext
from OpenGLContext.loaders.resolver import contained_source
from OpenGLContext.loaders.gltf.materials import (
    GLTF_TEXTURE_KEYS, MATERIAL_EXTENSION_FIELDS, khr_transform_params,
)
from OpenGLContext.loaders.basisu import BasisImage
from OpenGLContext.loaders.gltf.textures import (
    BASISU_EXTENSION, IMAGE_EXTENSIONS, VIDEO_EXTENSION, gl_sampler,
)
from OpenGLContext.scenegraph.movietexture import MovieTexture
from OpenGLContext.scenegraph.gaussiansplats import GaussianSplats
from OpenGLContext.scenegraph.imagedata import ImageDataTexture, x3d_image
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.physicalmaterial import (
    NO_ATTENUATION, ChannelMaterial, appearance_alpha, pbr_material, source_of,
)
from OpenGLContext.scenegraph.texturemapping import (
    channel_labels, coordinate_set, transform_for, transform_matrix,
)
from OpenGLContext.scenegraph.specularglossiness import SpecularGlossinessMaterial
from OpenGLContext.scenegraph.unlitmaterial import UnlitMaterial
from vrml.x3d import nodes as x3d

GENERATOR = "OpenGLContext %s glTF writer" % _engine_version

# glTF component types (equal to the GL enums they name).
BYTE, UNSIGNED_BYTE, SHORT, UNSIGNED_SHORT, UNSIGNED_INT, FLOAT = (
    5120, 5121, 5122, 5123, 5125, 5126)
# bufferView.target
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON, _CHUNK_BIN = 0x4E4F534A, 0x004E4942

# An index array narrower than this many vertices fits in 16 bits, which halves
# the index buffer of a typical terrain tile.
_SHORT_INDEX_LIMIT = 1 << 16

#: What a glTF mesh primitive is written from.
Primitive = Union[PBRMesh, GaussianSplats]
MeshLike = Union[PBRMesh, GaussianSplats, "SceneNode"]


# --- the scene description ----------------------------------------------------

@dataclass
class InstanceSet:
    """Per-instance transforms for ``EXT_mesh_gpu_instancing``.

    Each array holds one row per instance: ``translations`` (M,3),
    ``rotations`` (M,4) as xyzw quaternions, ``scales`` (M,3). Any may be
    omitted, and the ones supplied must agree on M. A node carrying this draws
    its mesh once per row, which is how a baked tile ships a forest of trees as
    one mesh and a table of placements.
    """

    translations: Optional[np.ndarray] = None
    rotations: Optional[np.ndarray] = None
    scales: Optional[np.ndarray] = None

    def count(self) -> int:
        """How many instances the set describes."""
        counts = {len(a) for a in (self.translations, self.rotations, self.scales)
                  if a is not None}
        if not counts:
            return 0
        if len(counts) > 1:
            raise ValueError(
                "instance arrays disagree on their length: %s"
                % ", ".join("%s=%d" % (name, len(arr)) for name, arr in (
                    ('translations', self.translations), ('rotations', self.rotations),
                    ('scales', self.scales)) if arr is not None))
        return counts.pop()


class EncodedImage(ImageDataTexture):
    """A texture whose image stays encoded, embedded without going through PIL

    A source JPEG stays a JPEG, at its authored size: re-encoding a
    photographic map as PNG multiplies a tile's weight for no gain in what it
    looks like. It is an :class:`ImageDataTexture`, so it goes in a material's
    texture field; the image is decoded the first time the texture is drawn.
    """

    PROTO = 'EncodedImage'

    def __init__(self, data: bytes = b'', mime_type: str = 'image/png', **named: Any) -> None:
        super().__init__(**named)
        self.data = bytes(data)
        self.mime_type = mime_type

    def cached(self, mode: Any = None) -> Any:
        """The GL texture, decoding the image the first time it is drawn"""
        if self.image is None and self.data:
            from PIL import Image  # noqa: PLC0415 decoded only when drawn
            self.image = Image.open(io.BytesIO(self.data))
        return super().cached(mode)

    def x3dEquivalent(self) -> Any:
        """An X3D `ImageTexture` of the image as a `data:` URL in its own format

        The image is re-encoded upside down, as X3D puts texture coordinate
        (0, 0) at an image's lower left and glTF at its upper left.
        """
        from PIL import Image  # noqa: PLC0415 decoded only when written
        decoded = Image.open(io.BytesIO(self.data))
        format = decoded.format or 'PNG'
        options = {'quality': 95} if format == 'JPEG' else {}
        return self.x3dTexture(self.mime_type, x3d_image(decoded, format, **options))

    @classmethod
    def from_path(cls, path: str, **named: Any) -> "EncodedImage":
        """Read an image file, taking its MIME type from the extension"""
        suffix = path.lower().rsplit('.', 1)[-1]
        mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                'webp': 'image/webp', 'avif': 'image/avif'}.get(suffix, 'image/png')
        with open(contained_source(path), 'rb') as handle:
            return cls(handle.read(), mime_type=mime, **named)


@dataclass
class SceneNode:
    """One node of the written hierarchy: a placed mesh, or a parent of nodes.

    ``mesh`` is a :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh`, a
    :class:`~OpenGLContext.scenegraph.gaussiansplats.GaussianSplats`, or a list
    of them sharing this node's placement (they become the primitives of one
    glTF mesh). The placement is either ``matrix`` (16 floats, column-major) or the
    ``translation``/``rotation``/``scale`` triple; a node giving both is refused,
    since glTF cannot express the pair. ``rotation`` is an xyzw quaternion.

    ``extras`` is written through as the node's ``extras``, which is the
    format's slot for what an application knows; ``hook`` is an ``OGLC_hook``
    block saying what the engine should make of this object
    (:mod:`OpenGLContext.loaders.gltf.hooks`).

    ``buffer`` names the file beside the ``.glb`` that this node's mesh data
    is written to, a plain file name such as ``'bust.lod0.bin'``; None, the
    default, writes it into the glB's own binary chunk. A reader fetches that
    file only when it reads the mesh, which is how a baked level-of-detail
    chain keeps its finer levels out of the file every reader opens.
    """

    mesh: Primitive | Sequence[Primitive] | None = None
    name: Optional[str] = None
    translation: Optional[Sequence[float]] = None
    rotation: Optional[Sequence[float]] = None
    scale: Optional[Sequence[float]] = None
    matrix: Optional[Sequence[float]] = None
    children: Sequence["SceneNode"] = dataclass_field(default_factory=list)
    instances: Optional[InstanceSet] = None
    extras: Optional[dict] = None
    hook: Optional[dict] = None
    buffer: Optional[str] = None


@dataclass(frozen=True)
class GlobalSound:
    """A sound heard wherever it is switched on: one ``KHR_audio_emitter``
    global emitter playing one audio file.

    ``uri`` is the file, relative to the document; ``mime_type`` its type
    (``KHR_audio_emitter`` names ``audio/mpeg``, and this engine also plays
    ``audio/wav``, Ogg and FLAC -- see ``docs/extensions/OGLC_zone.rst``);
    ``gain`` the emitter's level. A zone that plays one scales that gain by
    its weight, so the sound fades as the camera leaves.
    """

    name: str
    uri: str
    gain: float = 1.0
    mime_type: str = 'audio/wav'
    loop: bool = True
    autoplay: bool = True


def zone_box(size: Sequence[float]) -> dict:
    """A ``KHR_implicit_shapes`` box of full extents ``size`` (x, y, z), for
    :attr:`ZoneNode.shape`."""
    return {'type': 'box', 'box': {'size': [float(v) for v in size]}}


@dataclass
class ZoneNode:
    """An ``OGLC_zone`` node: a region, and what holds inside it.

    ``shape`` is a ``KHR_implicit_shapes`` shape object (:func:`zone_box`),
    centred on the node, which ``translation`` and ``rotation`` (an xyzw
    quaternion) place. ``priority`` and ``blend`` are the zone's rules;
    ``environment`` and ``reverb`` its own blocks as ``OGLC_zone`` defines
    them; ``sounds`` the :class:`GlobalSound` it plays. The format is
    ``docs/extensions/OGLC_zone.rst``, and
    :mod:`OpenGLContext.loaders.gltf.zoning` reads it.
    """

    name: str
    shape: dict
    translation: Sequence[float] = (0.0, 0.0, 0.0)
    rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0)
    priority: int = 0
    blend: float = 0.0
    environment: Optional[dict] = None
    reverb: Optional[dict] = None
    sounds: Sequence[GlobalSound] = ()


# --- accessors and buffer layout ----------------------------------------------

class _BufferBuilder:
    """Accumulates the buffers and the bufferViews/accessors into them.

    Each buffer is named by the file it is written to, ``None`` being the glB's
    own binary chunk. Every view starts on a four-byte boundary, which satisfies
    the alignment the spec asks of accessor offsets for all the component types
    written here.
    """

    def __init__(self) -> None:
        self.blobs: dict[Optional[str], bytearray] = {None: bytearray()}
        self.views: list[dict] = []
        self.view_buffers: list[Optional[str]] = []
        self.accessors: list[dict] = []

    @property
    def blob(self) -> bytearray:
        """The glB's binary chunk."""
        return self.blobs[None]

    def add_view(self, data: bytes, target: Optional[int] = None,
                 buffer: Optional[str] = None) -> int:
        blob = self.blobs.setdefault(buffer, bytearray())
        blob.extend(b'\x00' * (-len(blob) % 4))
        view = {'byteOffset': len(blob), 'byteLength': len(data)}
        if target is not None:
            view['target'] = target
        blob.extend(data)
        self.views.append(view)
        self.view_buffers.append(buffer)
        return len(self.views) - 1

    def buffers(self) -> tuple[list[dict], list[dict]]:
        """The document's ``buffers`` and ``bufferViews``.

        The binary chunk is buffer 0 when it holds anything, and a buffer that
        holds nothing is not listed, since glTF requires every buffer to hold
        at least a byte. The files follow in the order they were first named.
        """
        order = [name for name, blob in self.blobs.items() if blob]
        order.sort(key=lambda name: name is not None)
        listed = [({'byteLength': len(self.blobs[name])} if name is None else
                   {'uri': name, 'byteLength': len(self.blobs[name])})
                  for name in order]
        where = {name: index for index, name in enumerate(order)}
        views = [dict(view, buffer=where[name])
                 for view, name in zip(self.views, self.view_buffers)]
        return listed, views

    def add_accessor(self, array: np.ndarray, kind: str, component_type: int,
                     target: Optional[int] = None, normalized: bool = False,
                     bounds: bool = False, buffer: Optional[str] = None) -> int:
        data = np.ascontiguousarray(array).tobytes()
        accessor: dict[str, Any] = {
            'bufferView': self.add_view(data, target, buffer),
            'componentType': component_type,
            'count': int(len(array)),
            'type': kind,
        }
        if normalized:
            accessor['normalized'] = True
        if bounds and len(array):
            flat = array.reshape(len(array), -1)
            accessor['min'] = [float(v) for v in flat.min(axis=0)]
            accessor['max'] = [float(v) for v in flat.max(axis=0)]
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def add_floats(self, array: np.ndarray, kind: str, bounds: bool = False,
                   buffer: Optional[str] = None) -> int:
        return self.add_accessor(np.asarray(array, '<f4'), kind, FLOAT,
                                 target=ARRAY_BUFFER, bounds=bounds,
                                 buffer=buffer)


#: What an :class:`_IdentityCache` holds for each object.
_Value = TypeVar('_Value')


class _IdentityCache(Generic[_Value]):
    """Values (indices, mostly) already assigned to objects, keyed by identity.

    The cache holds a reference to each object it has seen. ``id()`` on its own
    is not a safe key: a mesh that is collected frees its address for the next
    allocation, and an unrelated second mesh at that address would then be
    handed the first one's index and written as a copy of it.
    """

    def __init__(self) -> None:
        self._entries: dict[int, tuple[Any, _Value]] = {}

    def get(self, obj: Any) -> Optional[_Value]:
        found = self._entries.get(id(obj))
        return found[1] if found is not None and found[0] is obj else None

    def set(self, obj: Any, value: _Value) -> _Value:
        self._entries[id(obj)] = (obj, value)
        return value


_VECTOR_KIND = {1: 'SCALAR', 2: 'VEC2', 3: 'VEC3', 4: 'VEC4'}


def _kind_for(array: np.ndarray, name: str, allowed: Sequence[int]) -> str:
    """The glTF accessor type for an (N,k) attribute, k validated."""
    width = 1 if array.ndim == 1 else int(array.shape[1])
    if width not in allowed:
        raise ValueError(
            "glTF attribute %s must have %s components per vertex, not %d"
            % (name, " or ".join(str(a) for a in allowed), width))
    return _VECTOR_KIND[width]


# --- materials ----------------------------------------------------------------

# Written when the field differs from the glTF default; the table is the
# reader's too (materials.MATERIAL_EXTENSION_FIELDS).
_MATERIAL_EXTENSIONS = MATERIAL_EXTENSION_FIELDS

# attenuationDistance is +inf in glTF; PhysicalMaterial holds that as
# NO_ATTENUATION, and 0 also means no absorption, so neither is written.
_SENTINEL_INFINITY = ('attenuationDistance',)

# Which extension a factor belongs to, so a non-default factor pulls its whole
# extension block in (a sheen roughness with no sheen colour is still sheen).
_MATERIAL_TEXTURE_EXTENSION = {
    'specular': 'KHR_materials_specular',
    'specularColor': 'KHR_materials_specular',
    'clearcoat': 'KHR_materials_clearcoat',
    'clearcoatRoughness': 'KHR_materials_clearcoat',
    'clearcoatNormal': 'KHR_materials_clearcoat',
    'sheenColor': 'KHR_materials_sheen',
    'sheenRoughness': 'KHR_materials_sheen',
    'transmission': 'KHR_materials_transmission',
    'thickness': 'KHR_materials_volume',
    'iridescence': 'KHR_materials_iridescence',
    'iridescenceThickness': 'KHR_materials_iridescence',
    'anisotropy': 'KHR_materials_anisotropy',
    'diffuseTransmission': 'KHR_materials_diffuse_transmission',
    'diffuseTransmissionColor': 'KHR_materials_diffuse_transmission',
    'retroreflection': 'KHR_materials_retroreflection',
    'scatterStrength': 'KHR_materials_scatter',
    'multiscatterColor': 'KHR_materials_scatter',
}

# The textureInfo key each extension gives its channel.
_EXTENSION_TEXTURE_KEY = {channel: key for channel, key in GLTF_TEXTURE_KEYS.items()
                          if channel in _MATERIAL_TEXTURE_EXTENSION}

# Ours: what a material or a node is, for the engine to make something of on
# load. The reader's half of the pair is in hooks, and so is the name.
_HOOK_EXTENSION = _hooks.EXTENSION


def texture_coordinates(appearance: Any, geometry: Any) -> "dict[str, tuple[int, Optional[dict]]]":
    """Each textured channel's coordinate set and KHR_texture_transform parameters

    Read from the material's mapping labels, the geometry's coordinate sets
    and the appearance's texture transforms, as the renderer reads them.
    """
    found: "dict[str, tuple[int, Optional[dict]]]" = {}
    material = getattr(appearance, 'material', None)
    for channel, label in channel_labels(material).items():
        transform = transform_for(appearance, label)
        params = None
        if transform is not None:
            affine = transform_matrix(transform)
            matrix = np.identity(4)
            matrix[0, [0, 1, 3]] = affine[0]
            matrix[1, [0, 1, 3]] = affine[1]
            params = khr_transform_params(matrix)
        found[channel] = (coordinate_set(geometry, label), params)
    return found


def _with_impostor(material: Any) -> "Optional[dict]":
    """A material's ``extras``, with its octahedral impostor's views where it is one

    ``extras`` is where the glTF loader reads ``octahedralViews`` and
    ``octahedralHemi`` from (:mod:`OpenGLContext.loaders.gltf.materials`).
    """
    extras = getattr(material, 'extras', None)
    views = int(getattr(material, 'octahedralViews', 0) or 0)
    if views < 2:
        return extras
    found = dict(extras) if isinstance(extras, dict) else {}
    found.update(octahedralViews=views,
                 octahedralHemi=bool(getattr(material, 'octahedralHemi', True)))
    return found


def _reflector_hook(material: Any) -> Any:
    """The ``mirror`` hook a material's reflector loads back from, or None.

    None for a material with no reflector, one switched off, and water's own,
    which the water hook puts back.
    """
    from OpenGLContext.scenegraph.reflector import WATER
    reflector = getattr(material, 'reflector', None)
    if not reflector or not reflector.enabled or reflector is WATER:
        return None
    from OpenGLContext.scenegraph import mirrorhooks
    return mirrorhooks.hook_for(reflector)


def _close(value: Any, default: Any) -> bool:
    """Whether a material field still holds its glTF default."""
    if isinstance(default, tuple):
        return bool(np.allclose(np.asarray(value, 'd'), np.asarray(default, 'd'),
                                atol=1e-6))
    return abs(float(value) - float(default)) <= 1e-6


def _factor(value: Any) -> Any:
    """A material field as JSON: a float, or a list for a colour."""
    flat = np.asarray(value, 'd').ravel()
    if flat.shape == (1,):
        return float(flat[0])
    return [float(v) for v in flat]


# --- the writer ---------------------------------------------------------------

#: The extension a texture needs for an image in each format the core does
#: not allow.
_IMAGE_EXTENSION = {mime: name for name, mime in IMAGE_EXTENSIONS}
_KTX2_IDENTIFIER = b'\xabKTX 20\xbb\r\n\x1a\n'


class GLTFWriter:
    """Builds a glTF 2.0 document and serializes it as GLB.

    Add meshes and nodes in any order -- ``add_mesh`` and ``add_node`` return the
    index the document gives each one -- then call :meth:`to_glb` for the bytes or
    :meth:`write` to put them on disk. Meshes and materials passed twice are
    written once and referenced twice, so a scatter of a thousand identical props
    costs one mesh.

    Nodes added with no parent become roots of the default scene. ``extras``
    is written as the document's own ``extras``.
    """

    def __init__(self, generator: str = GENERATOR) -> None:
        self._generator = generator
        self._buffer = _BufferBuilder()
        self._meshes: list[dict] = []
        self._materials: list[dict] = []
        self._textures: list[dict] = []
        self._samplers: list[dict] = []
        self._images: list[dict] = []
        self._nodes: list[dict] = []
        self._roots: list[int] = []
        self._extensions_used: set[str] = set()
        self._extensions_required: set[str] = set()
        #: Each image index written in a format only an extension allows.
        self._image_extension: dict[int, str] = {}
        self._mesh_index: _IdentityCache[int] = _IdentityCache()
        #: Each material's glTF indices, one per alpha mode, cutoff and sidedness.
        self._material_index: _IdentityCache[dict[tuple, int]] = _IdentityCache()
        self._image_index: _IdentityCache[int] = _IdentityCache()
        self._texture_index: dict[tuple, int] = {}
        #: Written as the document's ``extras`` when it holds anything.
        self.extras: dict = {}
        self._shapes: list[dict] = []
        self._sounds: list[GlobalSound] = []
        #: EXT_texture_video uris, in the order the textures first name them.
        self._videos: list[str] = []
        #: The directory :meth:`write` is writing into, while it writes.
        self._directory: Optional[str] = None
        #: KHR_materials_variants names, in the order the meshes first map them.
        self._variant_names: list[str] = []

    # -- meshes ----------------------------------------------------------------

    def add_mesh(self, mesh: Primitive | Sequence[Primitive],
                 name: Optional[str] = None,
                 buffer: Optional[str] = None) -> int:
        """Write one mesh (or a group of primitives) and return its index.

        Each primitive is a :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh`,
        or a :class:`~OpenGLContext.scenegraph.gaussiansplats.GaussianSplats`
        written as a ``KHR_gaussian_splatting`` primitive. Passing the same
        object again returns the index already assigned to it. ``buffer`` is
        the file beside the ``.glb`` its arrays go to, as :attr:`SceneNode.buffer`.
        """
        _check_buffer_name(buffer)
        primitives_source = ([mesh] if isinstance(mesh, (PBRMesh, GaussianSplats))
                             else list(mesh))
        if len(primitives_source) == 1:
            cached = self._mesh_index.get(primitives_source[0])
            if cached is not None:
                return cached
        entry: dict[str, Any] = {
            'primitives': [self._primitive(m, buffer) for m in primitives_source]}
        if name:
            entry['name'] = name
        self._meshes.append(entry)
        index = len(self._meshes) - 1
        if len(primitives_source) == 1:
            self._mesh_index.set(primitives_source[0], index)
        return index

    def _primitive(self, mesh: Primitive, buffer: Optional[str] = None) -> dict:
        if isinstance(mesh, GaussianSplats):
            splat, extension = splat_primitive(
                mesh, lambda array, kind, bounds: self._buffer.add_floats(
                    array, kind, bounds=bounds, buffer=buffer))
            self._extensions_used.add(extension)
            return splat
        positions = np.asarray(mesh.positions, '<f4')
        if positions.ndim != 2 or positions.shape[1] != 3 or not len(positions):
            raise ValueError("a glTF primitive needs a non-empty (N,3) POSITION array")
        count = len(positions)
        attributes = {'POSITION': self._buffer.add_floats(
            positions, 'VEC3', bounds=True, buffer=buffer)}

        for name, source, allowed in (
                ('NORMAL', mesh.normals, (3,)),
                ('TEXCOORD_0', mesh.texcoords, (2,)),
                ('TEXCOORD_1', getattr(mesh, 'texcoords1', None), (2,)),
                ('TANGENT', mesh.tangents, (4,)),
                ('COLOR_0', mesh.colors, (3, 4))):
            if source is None:
                continue
            array = np.asarray(source, '<f4')
            if len(array) != count:
                raise ValueError(
                    "glTF attribute %s has %d entries but POSITION has %d"
                    % (name, len(array), count))
            attributes[name] = self._buffer.add_floats(
                array, _kind_for(array, name, allowed), buffer=buffer)

        primitive: dict[str, Any] = {'attributes': attributes}
        indices = getattr(mesh, 'indices', None)
        if indices is not None and len(indices):
            indices = np.asarray(indices).ravel()
            if int(indices.max()) >= count:
                raise ValueError(
                    "glTF primitive index %d is out of range for %d vertices"
                    % (int(indices.max()), count))
            narrow = count < _SHORT_INDEX_LIMIT
            primitive['indices'] = self._buffer.add_accessor(
                indices.astype('<u2' if narrow else '<u4'), 'SCALAR',
                UNSIGNED_SHORT if narrow else UNSIGNED_INT,
                target=ELEMENT_ARRAY_BUFFER, buffer=buffer)
        mode = int(getattr(mesh, 'draw_mode', 4) or 0)
        if mode != 4:                                    # TRIANGLES is the default
            primitive['mode'] = mode
        dressed = getattr(mesh, 'materialVariants', None)
        appearance, solid = (dressed.default if dressed is not None else
                             (getattr(mesh, 'appearance', None),
                              bool(getattr(mesh, 'solid', True))))
        material = self._appearance_material(mesh, appearance, solid)
        if material is not None:
            primitive['material'] = material
        if dressed is not None and dressed.by_name:
            primitive.setdefault('extensions', {})[variantsext.EXTENSION] = {
                'mappings': self._variant_mappings(mesh, dressed)}
            self._extensions_used.add(variantsext.EXTENSION)
        return primitive

    def _appearance_material(self, mesh: Any, appearance: Any,
                             solid: bool) -> Optional[int]:
        """The material index for ``mesh`` drawn in ``appearance``, or None."""
        material = getattr(appearance, 'material', None)
        if isinstance(material, ChannelMaterial):
            # With the appearance's texture as the base map where it stands in
            # for the material's own.
            material = pbr_material(appearance)
        if not material:
            return None
        return self.add_material(
            material, alpha=appearance_alpha(appearance), double_sided=not solid,
            coordinates=texture_coordinates(appearance, mesh))

    def _variant_mappings(self, mesh: Any, dressed: Any) -> list[dict]:
        """``KHR_materials_variants`` mappings: one per material, listing the
        variants (indices into the document's variant names) that choose it."""
        by_material: dict[int, list[int]] = {}
        for name, (appearance, solid) in dressed.by_name.items():
            material = self._appearance_material(mesh, appearance, solid)
            if material is None:
                continue
            if name not in self._variant_names:
                self._variant_names.append(name)
            by_material.setdefault(material, []).append(self._variant_names.index(name))
        return [{'material': material, 'variants': sorted(variants)}
                for material, variants in by_material.items()]

    # -- materials -------------------------------------------------------------

    def add_material(self, material: Any, name: Optional[str] = None,
                     alpha: "tuple[str, float]" = ('OPAQUE', 0.5),
                     double_sided: bool = False,
                     coordinates: "Optional[dict[str, tuple[int, Optional[dict]]]]" = None,
                     ) -> int:
        """Write a `PhysicalMaterial`, `SpecularGlossinessMaterial` or `UnlitMaterial` as a glTF material

        alpha -- the alpha mode and cutoff, which X3D puts on the Appearance
        double_sided -- True for geometry that is not `solid`
        coordinates -- each channel's texture coordinate set and
            KHR_texture_transform parameters (or None), which X3D gives with
            mapping labels on the material, geometry and appearance
            (:func:`texture_coordinates`)

        glTF puts all of these on the material, so one material drawn two
        ways is two glTF materials. Returns the index; the same material, alpha and
        sidedness again reuse it. Without a ``name``, the material's own
        ``DEF`` is written as the glTF material name, so a material a caller
        can address by name in one document is addressable by that name in the
        document written from it.
        """
        variants = self._material_index.get(material)
        if variants is None:
            variants = self._material_index.set(material, {})
        coordinates = coordinates or {}
        key = (alpha[0], round(float(alpha[1]), 6), bool(double_sided),
               json.dumps(coordinates, sort_keys=True))
        cached = variants.get(key)
        if cached is not None:
            return cached
        entry = self._material_json(material, name or getattr(material, 'DEF', '') or None,
                                    coordinates)
        if alpha[0] != 'OPAQUE':
            entry['alphaMode'] = alpha[0]
        if alpha[0] == 'MASK':
            entry['alphaCutoff'] = float(alpha[1])
        if double_sided:
            entry['doubleSided'] = True
        self._materials.append(entry)
        index = variants[key] = len(self._materials) - 1
        return index

    def _material_json(self, material: Any, name: Optional[str],
                       coordinates: "dict[str, tuple[int, Optional[dict]]]") -> dict:
        textures = dict(getattr(material, 'textures', None) or {})

        def texture_info(channel: str) -> Optional[dict]:
            holder = textures.get(channel)
            if holder is None:
                return None
            info: dict[str, Any] = {'index': self._add_texture(holder)}
            chosen, transform = coordinates.get(channel, (0, None))
            if chosen:
                info['texCoord'] = chosen
            if transform is not None:
                info['extensions'] = {'KHR_texture_transform': transform}
                self._extensions_used.add('KHR_texture_transform')
            return info

        alpha = 1.0 - float(getattr(material, 'transparency', 0.0))
        if isinstance(source_of(material), UnlitMaterial):
            pbr: dict[str, Any] = {
                'baseColorFactor': [float(c) for c in material.emissiveColor] + [alpha],
                'metallicFactor': 0.0, 'roughnessFactor': 1.0}
            base_color = texture_info('baseColor')
            if base_color is not None:
                pbr['baseColorTexture'] = base_color
            entry: dict[str, Any] = {'pbrMetallicRoughness': pbr,
                                     'extensions': {'KHR_materials_unlit': {}}}
            self._extensions_used.add('KHR_materials_unlit')
            if name:
                entry['name'] = name
            self._carry_extras(entry, _with_impostor(material))
            return entry
        glossy = isinstance(source_of(material), SpecularGlossinessMaterial)
        if glossy:
            # The specular/glossiness workflow, with no metallic/roughness
            # fallback: a reader draws it as written or not at all.
            block: dict[str, Any] = {
                'diffuseFactor': [float(c) for c in material.diffuseColor] + [alpha],
                'specularFactor': [float(c) for c in material.specularColor],
                'glossinessFactor': float(material.glossiness),
            }
            for channel, key in (('baseColor', 'diffuseTexture'),
                                 ('specularColor', 'specularGlossinessTexture')):
                found = texture_info(channel)
                if found is not None:
                    block[key] = found
            entry = {'extensions': {'KHR_materials_pbrSpecularGlossiness': block}}
            self._extensions_used.add('KHR_materials_pbrSpecularGlossiness')
        else:
            pbr = {
                'baseColorFactor': [float(c) for c in material.baseColor] + [alpha],
                'metallicFactor': float(material.metallic),
                'roughnessFactor': float(material.roughness),
            }
            base_color = texture_info('baseColor')
            if base_color is not None:
                pbr['baseColorTexture'] = base_color
            metallic_roughness = texture_info('metallicRoughness')
            if metallic_roughness is not None:
                pbr['metallicRoughnessTexture'] = metallic_roughness
            entry = {'pbrMetallicRoughness': pbr}
        if name:
            entry['name'] = name
        emissive = [float(c) for c in getattr(material, 'emissiveColor', (0, 0, 0))]
        if any(abs(c) > 1e-6 for c in emissive):
            entry['emissiveFactor'] = emissive

        normal = texture_info('normal')
        if normal is not None:
            scale = float(getattr(material, 'normalScale', 1.0))
            entry['normalTexture'] = dict(normal, scale=scale) if scale != 1.0 else normal
        occlusion = texture_info('occlusion')
        if occlusion is not None:
            strength = float(getattr(material, 'occlusionStrength', 1.0))
            entry['occlusionTexture'] = (dict(occlusion, strength=strength)
                                         if strength != 1.0 else occlusion)
        emissive_texture = texture_info('emissive')
        if emissive_texture is not None:
            entry['emissiveTexture'] = emissive_texture

        extensions = {} if glossy else self._material_extensions(material, texture_info)
        extensions.update(self._hook_extension(
            getattr(material, 'hook', None) or _reflector_hook(material)))
        if extensions:
            entry.setdefault('extensions', {}).update(extensions)
            self._extensions_used.update(extensions)
        self._carry_extras(entry, _with_impostor(material))
        return entry

    def _hook_extension(self, hook: Any) -> dict:
        """An ``OGLC_hook`` block for a material or node that carries one.

        A dict naming a ``kind``, or the kind on its own. What the loader read
        off a document comes back here, so a world loaded, edited and baked
        again keeps what it was tagged as.
        """
        if isinstance(hook, str) and hook.strip():
            hook = {'kind': hook.strip()}
        if not isinstance(hook, dict) or not hook.get('kind'):
            return {}
        return {_HOOK_EXTENSION: dict(hook)}

    @staticmethod
    def _carry_extras(entry: dict, extras: Any) -> None:
        """Write an object's ``extras`` through, where it has any.

        The format's own slot for what an application knows, and a reader that
        does not know it is meant to step over it -- so what is written is what
        was given, uninterpreted.
        """
        if isinstance(extras, dict) and extras:
            entry['extras'] = dict(extras)

    def _material_extensions(self, material: Any, texture_info: Any) -> dict:
        """The ``KHR_materials_*`` blocks whose factors or maps are not default."""
        textures = dict(getattr(material, 'textures', None) or {})
        wanted: dict[str, dict] = {}
        for channel in textures:
            extension = _MATERIAL_TEXTURE_EXTENSION.get(channel)
            if extension:
                wanted.setdefault(extension, {})
        for extension, fields in _MATERIAL_EXTENSIONS:
            block: dict[str, Any] = {}
            for key, (attribute, default) in fields.items():
                value = getattr(material, attribute, default)
                if attribute in _SENTINEL_INFINITY and (_close(value, 0.0)
                                                        or value >= NO_ATTENUATION):
                    continue
                if not _close(value, default):
                    block[key] = _factor(value)
            if extension == 'OGLC_materials_baked_light':
                if bool(getattr(material, 'bakedLight', False)):
                    wanted[extension] = {}
                continue
            if block or extension in wanted:
                wanted.setdefault(extension, {}).update(block)
        for channel, key in _EXTENSION_TEXTURE_KEY.items():
            extension = _MATERIAL_TEXTURE_EXTENSION.get(channel)
            if extension in wanted and channel in textures:
                info = texture_info(channel)
                if info is not None:
                    wanted[extension][key] = info
        coat = wanted.get('KHR_materials_clearcoat', {}).get('clearcoatNormalTexture')
        scale = float(getattr(material, 'clearcoatNormalScale', 1.0))
        if coat is not None and not _close(scale, 1.0):
            coat['scale'] = _factor(scale)
        return wanted

    # -- textures --------------------------------------------------------------

    def _add_texture(self, holder: Any) -> int:
        if isinstance(holder, MovieTexture):
            return self._add_video(holder)
        sampler = self._add_sampler(holder)
        image = self._add_image(holder)
        key = (image, sampler)
        cached = self._texture_index.get(key)
        if cached is not None:
            return cached
        entry: dict[str, Any] = {'source': image}
        extension = self._image_extension.get(image)
        if extension is not None:
            # The only image there is, in a format the core does not allow, so
            # the document requires the extension.
            entry = {'extensions': {extension: {'source': image}}}
            self._extensions_used.add(extension)
            self._extensions_required.add(extension)
        if sampler is not None:
            entry['sampler'] = sampler
        self._textures.append(entry)
        index = len(self._textures) - 1
        self._texture_index[key] = index
        return index

    def _add_video(self, holder: Any) -> int:
        """A MovieTexture as an ``EXT_texture_video`` texture naming its first url

        It has no still image to fall back to, so the document requires the
        extension.
        """
        urls = [str(url) for url in holder.url]
        if not urls:
            raise ValueError('A MovieTexture with no url has no video to write')
        if urls[0] not in self._videos:
            self._videos.append(urls[0])
        entry = {'extensions': {VIDEO_EXTENSION: {'source': self._videos.index(urls[0])}}}
        self._extensions_used.add(VIDEO_EXTENSION)
        self._extensions_required.add(VIDEO_EXTENSION)
        self._textures.append(entry)
        return len(self._textures) - 1

    def _add_image(self, holder: Any) -> int:
        """A texture's image: an ImageTexture's first URL as a uri, else embedded

        An ``EncodedImage`` is embedded as its bytes, an AVIF or WebP one
        through its texture's ``EXT_texture_avif`` or ``EXT_texture_webp``
        (:meth:`_add_texture`); any other image is encoded as PNG.
        """
        if isinstance(holder, x3d.ImageTexture):
            cached = self._image_index.get(holder)
            if cached is not None:
                return cached
            urls = list(holder.url)
            if not urls:
                raise ValueError('An ImageTexture with no url has no image to write')
            self._images.append({'uri': urls[0]})
            return self._image_index.set(holder, len(self._images) - 1)
        if isinstance(holder, EncodedImage):
            cached = self._image_index.get(holder)
            if cached is not None:
                return cached
            view = self._buffer.add_view(holder.data)
            self._images.append({'bufferView': view, 'mimeType': holder.mime_type})
            index = self._image_index.set(holder, len(self._images) - 1)
            extension = _IMAGE_EXTENSION.get(holder.mime_type)
            if extension is not None:
                self._image_extension[index] = extension
            return index
        image = holder.image
        cached = self._image_index.get(image)
        if cached is not None:
            return cached
        if isinstance(image, BasisImage) and image.data[:12] == _KTX2_IDENTIFIER:
            # The file as it came, under the extension that carries it; there
            # is no PNG beside it, so the document requires the extension.
            view = self._buffer.add_view(image.data)
            self._images.append({'bufferView': view, 'mimeType': 'image/ktx2'})
            index = self._image_index.set(image, len(self._images) - 1)
            self._image_extension[index] = BASISU_EXTENSION
            return index
        if isinstance(image, BasisImage):
            image = image.pil()
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        view = self._buffer.add_view(buffer.getvalue())
        self._images.append({'bufferView': view, 'mimeType': 'image/png'})
        return self._image_index.set(image, len(self._images) - 1)

    def _add_sampler(self, holder: Any) -> Optional[int]:
        """The sampler for a texture's boundary modes and filters, or None for defaults"""
        entry = gl_sampler(holder)
        if not entry:
            return None
        for index, existing in enumerate(self._samplers):
            if existing == entry:
                return index
        self._samplers.append(entry)
        return len(self._samplers) - 1

    # -- nodes -----------------------------------------------------------------

    def add_node(self, node: Optional[SceneNode] = None, *, root: bool = True,
                 **kwargs: Any) -> int:
        """Write a :class:`SceneNode` (or its keyword equivalent); return its index.

        ``root=False`` keeps the node out of the scene's root list, for a caller
        assembling a hierarchy from the leaves up.
        """
        if node is None:
            node = SceneNode(**kwargs)
        elif kwargs:
            raise TypeError("pass a SceneNode or its fields, not both")
        entry = self._node_entry(node)
        self._nodes.append(entry)
        index = len(self._nodes) - 1
        if root:
            self._roots.append(index)
        return index

    def add_lod(self, levels: Sequence[SceneNode],
                coverage: Optional[Sequence[float]] = None, *,
                root: bool = True) -> int:
        """Write one object at several levels of detail; return its node's index.

        ``levels`` are finest first. The finest is written as the node carrying
        ``MSFT_lod``, whose ``ids`` name the others in decreasing detail, so a
        reader that does not know the extension draws the finest, and this
        engine's loader switches between them
        (:mod:`OpenGLContext.loaders.gltf.lod`). The coarser levels are placed
        where the finest is; their own transforms are not applied on top.

        ``coverage`` is ``MSFT_screencoverage``, one share of the window's
        height per level, decreasing: each level is drawn from its figure down
        to the next, and nothing below the last. None writes
        :func:`~OpenGLContext.loaders.gltf.lod.halving_coverage`, which ends at
        0 so the coarsest level is never culled.

        The finest level's node comes before the others, so a chain written
        into an empty writer is node 0 with ``ids`` 1 onwards.
        """
        from OpenGLContext.loaders.gltf import lod as _lod
        levels = list(levels)
        if not levels:
            raise ValueError("an object needs at least one level of detail")
        stated = (_lod.halving_coverage(len(levels)) if coverage is None
                  else [float(value) for value in coverage])
        if len(stated) != len(levels):
            raise ValueError("%d levels need %d coverage figures, not %d"
                             % (len(levels), len(levels), len(stated)))
        index = len(self._nodes)
        self._nodes.append({})
        if root:
            self._roots.append(index)
        # Meshes in decreasing detail, as the nodes are.
        for level in levels:
            if isinstance(level.mesh, PBRMesh):
                self.add_mesh(level.mesh, buffer=level.buffer)
        ids = [self.add_node(level, root=False) for level in levels[1:]]
        entry = self._node_entry(levels[0])
        entry.setdefault('extensions', {})[_lod.EXTENSION] = {'ids': ids}
        entry.setdefault('extras', {})[_lod.COVERAGE] = stated
        self._extensions_used.add(_lod.EXTENSION)
        self._nodes[index] = entry
        return index

    def add_zone(self, zone: ZoneNode, *, root: bool = True) -> int:
        """Write an ``OGLC_zone`` node; return its index.

        The zone's shape joins the document's ``KHR_implicit_shapes`` table and
        each sound it plays the ``KHR_audio_emitter`` arrays, a sound several
        zones play once.
        """
        block: dict[str, Any] = {'shape': len(self._shapes),
                                 'priority': int(zone.priority),
                                 'blend': float(zone.blend)}
        self._shapes.append(dict(zone.shape))
        self._extensions_used.update(('OGLC_zone', 'KHR_implicit_shapes'))
        if zone.environment is not None:
            block['environment'] = zone.environment
        if zone.reverb is not None:
            block['reverb'] = zone.reverb
        if zone.sounds:
            emitters = []
            for sound in zone.sounds:
                if sound not in self._sounds:
                    self._sounds.append(sound)
                emitters.append(self._sounds.index(sound))
            block['extensions'] = {'KHR_audio_emitter': {'emitters': emitters}}
            self._extensions_used.add('KHR_audio_emitter')
        self._nodes.append({
            'name': zone.name,
            'translation': [float(v) for v in zone.translation],
            'rotation': [float(v) for v in zone.rotation],
            'extensions': {'OGLC_zone': block}})
        index = len(self._nodes) - 1
        if root:
            self._roots.append(index)
        return index

    def _document_extensions(self) -> dict:
        """The document-level blocks: material variant names, and what the zones
        and their sounds need."""
        extensions: dict[str, Any] = {}
        if self._videos:
            extensions[VIDEO_EXTENSION] = {'videos': [
                {'uri': self._relative(uri)} for uri in self._videos]}
        if self._variant_names:
            extensions[variantsext.EXTENSION] = {
                'variants': [{'name': name} for name in self._variant_names]}
        if self._shapes:
            extensions['KHR_implicit_shapes'] = {'shapes': self._shapes}
        if self._sounds:
            extensions['KHR_audio_emitter'] = {
                'audio': [{'uri': sound.uri, 'mimeType': sound.mime_type}
                          for sound in self._sounds],
                'sources': [{'name': sound.name, 'audio': index,
                             'loop': sound.loop, 'autoplay': sound.autoplay}
                            for index, sound in enumerate(self._sounds)],
                'emitters': [{'name': sound.name, 'type': 'global',
                              'gain': float(sound.gain), 'sources': [index]}
                             for index, sound in enumerate(self._sounds)],
            }
        return extensions

    def _node_entry(self, node: SceneNode) -> dict:
        """One node's JSON, with its children and mesh written."""
        entry: dict[str, Any] = {}
        if node.name:
            entry['name'] = node.name
        if node.matrix is not None:
            if node.translation is not None or node.rotation is not None \
                    or node.scale is not None:
                raise ValueError(
                    "a glTF node states either a matrix or translation/rotation/"
                    "scale, not both")
            entry['matrix'] = [float(v) for v in np.asarray(node.matrix).ravel()]
        else:
            for key, value in (('translation', node.translation),
                               ('rotation', node.rotation), ('scale', node.scale)):
                if value is not None:
                    entry[key] = [float(v) for v in value]
        if node.mesh is not None:
            entry['mesh'] = self.add_mesh(node.mesh, buffer=node.buffer)
        if node.instances is not None:
            entry.setdefault('extensions', {})['EXT_mesh_gpu_instancing'] = \
                self._instancing(node.instances)
            self._extensions_used.add('EXT_mesh_gpu_instancing')
        hook = self._hook_extension(node.hook)
        if hook:
            entry.setdefault('extensions', {}).update(hook)
            self._extensions_used.update(hook)
        self._carry_extras(entry, node.extras)
        if node.children:
            entry['children'] = [self.add_node(child, root=False)
                                 for child in node.children]
        return entry

    def _instancing(self, instances: InstanceSet) -> dict:
        count = instances.count()
        if not count:
            raise ValueError("an instanced node needs at least one instance")
        attributes = {}
        for key, array, kind in (('TRANSLATION', instances.translations, 'VEC3'),
                                 ('ROTATION', instances.rotations, 'VEC4'),
                                 ('SCALE', instances.scales, 'VEC3')):
            if array is None:
                continue
            attributes[key] = self._buffer.add_floats(np.asarray(array, '<f4'), kind)
        return {'attributes': attributes}

    # -- output ----------------------------------------------------------------

    def document(self) -> dict:
        """The glTF JSON document, with the binary chunk left implicit."""
        doc: dict[str, Any] = {
            'asset': {'version': '2.0', 'generator': self._generator},
            'scene': 0,
            'scenes': [{'nodes': list(self._roots)}],
        }
        buffers, views = self._buffer.buffers()
        for key, value in (('nodes', self._nodes), ('meshes', self._meshes),
                           ('materials', self._materials), ('textures', self._textures),
                           ('images', self._images), ('samplers', self._samplers),
                           ('accessors', self._buffer.accessors),
                           ('bufferViews', views), ('buffers', buffers)):
            if value:
                doc[key] = value
        if self._extensions_used:
            doc['extensionsUsed'] = sorted(self._extensions_used)
        if self._extensions_required:
            doc['extensionsRequired'] = sorted(self._extensions_required)
        extensions = self._document_extensions()
        if extensions:
            doc['extensions'] = extensions
        if self.extras:
            doc['extras'] = self.extras
        return doc

    def to_glb(self) -> bytes:
        """The document as binary glTF.

        Mesh data written to a named buffer is not in it; see
        :meth:`external_buffers`.
        """
        return _pack_glb(self.document(), bytes(self._buffer.blob))

    def to_gltf(self) -> bytes:
        """The document as ``.gltf`` JSON text, UTF-8 encoded.

        For a document with no binary chunk -- zones, a scene of references --
        which is read as text; one holding mesh or image data in the chunk
        raises ``ValueError`` and is written with :meth:`to_glb`.
        """
        if self._buffer.blob:
            raise ValueError('this document holds %d bytes of binary chunk; '
                             'write it as a .glb' % (len(self._buffer.blob),))
        return (json.dumps(self.document(), indent=1) + '\n').encode('utf-8')

    def external_buffers(self) -> dict[str, bytes]:
        """The bytes of each file the document names beside itself, by name."""
        return {name: bytes(blob) for name, blob in self._buffer.blobs.items()
                if name is not None and blob}

    def write(self, path: str) -> bytes:
        """Write the document to ``path`` and return the glB's bytes.

        Each named buffer is written beside it. Every file is written whole
        or not at all (:mod:`OpenGLContext.atomicfiles`), the named buffers
        first, so a ``.glb`` on disk has its buffers beside it.
        """
        from OpenGLContext import atomicfiles
        directory = os.path.dirname(os.path.abspath(path))
        for name, data in self.external_buffers().items():
            atomicfiles.write_bytes(os.path.join(directory, name), data)
        self._directory = directory
        try:
            data = self.to_glb()
        finally:
            self._directory = None
        atomicfiles.write_bytes(path, data)
        return data

    def _relative(self, location: str) -> str:
        """A file ``location`` as a uri relative to the file being written,
        where it is under that file's directory; otherwise as it is."""
        directory = self._directory
        if directory is None or '://' in location or not os.path.isabs(location):
            return location
        inside = os.path.relpath(location, directory)
        if inside.startswith(os.pardir):
            return location
        return inside.replace(os.sep, '/')


def _check_buffer_name(name: Optional[str]) -> None:
    """Refuse a buffer name that is not a plain file name beside the ``.glb``.

    The name is written into the document as a relative ``uri`` and the file
    beside the ``.glb`` it is written to, and a reader resolves it under the
    ``.glb``'s own directory, so anything with a directory in it is refused.
    """
    if name is None:
        return
    if (not name or name in ('.', '..') or os.path.basename(name) != name
            or '\\' in name or ':' in name or '%' in name):
        raise ValueError("a buffer is named by a plain file name beside the "
                         ".glb, not %r" % (name,))


def _pack_glb(document: dict, blob: bytes) -> bytes:
    """Wrap a JSON document and its binary buffer in the GLB container.

    The JSON chunk pads with spaces and the binary chunk with zeroes, both to a
    four-byte boundary, as §4.4.1 of the specification requires.
    """
    json_chunk = json.dumps(document, separators=(',', ':')).encode('utf-8')
    json_chunk += b' ' * (-len(json_chunk) % 4)
    chunks = [(_CHUNK_JSON, json_chunk)]
    if blob:
        chunks.append((_CHUNK_BIN, blob + b'\x00' * (-len(blob) % 4)))
    length = 12 + sum(8 + len(data) for _, data in chunks)
    out = bytearray(struct.pack('<III', _GLB_MAGIC, 2, length))
    for kind, data in chunks:
        out.extend(struct.pack('<II', len(data), kind))
        out.extend(data)
    return bytes(out)


def write_glb(content: MeshLike | Iterable[MeshLike],
              path: Optional[str] = None, generator: str = GENERATOR) -> bytes:
    """Write meshes or nodes as a ``.glb`` and return the bytes.

    ``content`` is a :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh`, a
    :class:`~OpenGLContext.scenegraph.gaussiansplats.GaussianSplats`, a
    :class:`SceneNode`, or any iterable of them; a bare mesh is placed at the
    origin. With ``path``, the bytes are also written there.
    """
    items = ([content] if isinstance(content, (PBRMesh, GaussianSplats, SceneNode))
             else list(content))
    writer = GLTFWriter(generator=generator)
    for item in items:
        writer.add_node(item if isinstance(item, SceneNode) else SceneNode(mesh=item))
    if path is not None:
        return writer.write(path)
    return writer.to_glb()
