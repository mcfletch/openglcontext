"""glTF 2.0 writer: scenegraph meshes and PBR materials out as a ``.glb``.

The counterpart to :mod:`OpenGLContext.loaders.gltf.loader`. It takes the same
objects the loader produces -- :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh`
geometry and :class:`~OpenGLContext.scenegraph.pbrmaterial.PBRMaterial` materials
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
images with their samplers, a node hierarchy, and GPU instancing. Skinning,
animation and morph targets are not written; a document that needs them is
authored elsewhere.

Sources: the glTF 2.0 specification (§3 the asset, §4 the binary container,
§5 concepts) and the Khronos extension registry.
"""
from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Iterable, Optional, Sequence, Union

import numpy as np

from OpenGLContext import __version__ as _engine_version
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

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

MeshLike = Union[PBRMesh, "SceneNode"]


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


@dataclass
class EncodedImage:
    """A texture that is already encoded, embedded without going through PIL.

    Stands in for a :class:`~OpenGLContext.scenegraph.pbrmaterial.PBRTexture`
    anywhere a material names one. A source JPEG stays a JPEG, at its authored
    size: re-encoding a photographic map as PNG multiplies a tile's weight for
    no gain in what it looks like. The sampler fields carry the GL enums glTF
    uses, exactly as ``PBRTexture`` does.
    """

    data: bytes
    mime_type: str = 'image/png'
    srgb: bool = False
    wrap_s: Optional[int] = None
    wrap_t: Optional[int] = None
    min_filter: Optional[int] = None
    mag_filter: Optional[int] = None

    @classmethod
    def from_path(cls, path: str, **kwargs: Any) -> "EncodedImage":
        """Read an image file, taking its MIME type from the extension."""
        suffix = path.lower().rsplit('.', 1)[-1]
        mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'png': 'image/png', 'webp': 'image/webp'}.get(suffix, 'image/png')
        with open(path, 'rb') as handle:
            return cls(handle.read(), mime_type=mime, **kwargs)


@dataclass
class ExternalImage:
    """A texture stored beside the document rather than inside it.

    Written as an image ``uri``, which the loader resolves relative to the
    document. This is how a texture is shared: a tileset whose thousand tiles
    all use one road surface embeds it a thousand times if each document
    carries its own copy, and names it a thousand times if they point at one
    file. ``uri`` is relative to the written document unless it is absolute.

    Nothing here writes the file -- whatever produces the tiles is responsible
    for putting the image where the ``uri`` says it is.
    """

    uri: str
    srgb: bool = False
    wrap_s: Optional[int] = None
    wrap_t: Optional[int] = None
    min_filter: Optional[int] = None
    mag_filter: Optional[int] = None


@dataclass
class SceneNode:
    """One node of the written hierarchy: a placed mesh, or a parent of nodes.

    ``mesh`` is a :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` or a list of
    them sharing this node's placement (they become the primitives of one glTF
    mesh). The placement is either ``matrix`` (16 floats, column-major) or the
    ``translation``/``rotation``/``scale`` triple; a node giving both is refused,
    since glTF cannot express the pair. ``rotation`` is an xyzw quaternion.
    """

    mesh: Union[PBRMesh, Sequence[PBRMesh], None] = None
    name: Optional[str] = None
    translation: Optional[Sequence[float]] = None
    rotation: Optional[Sequence[float]] = None
    scale: Optional[Sequence[float]] = None
    matrix: Optional[Sequence[float]] = None
    children: Sequence["SceneNode"] = dataclass_field(default_factory=list)
    instances: Optional[InstanceSet] = None


# --- accessors and buffer layout ----------------------------------------------

class _BufferBuilder:
    """Accumulates the binary chunk and the bufferViews/accessors into it.

    Every view starts on a four-byte boundary, which satisfies the alignment the
    spec asks of accessor offsets for all the component types written here.
    """

    def __init__(self) -> None:
        self.blob = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []

    def add_view(self, data: bytes, target: Optional[int] = None) -> int:
        self.blob.extend(b'\x00' * (-len(self.blob) % 4))
        view = {'buffer': 0, 'byteOffset': len(self.blob), 'byteLength': len(data)}
        if target is not None:
            view['target'] = target
        self.blob.extend(data)
        self.views.append(view)
        return len(self.views) - 1

    def add_accessor(self, array: np.ndarray, kind: str, component_type: int,
                     target: Optional[int] = None, normalized: bool = False,
                     bounds: bool = False) -> int:
        data = np.ascontiguousarray(array).tobytes()
        accessor: dict[str, Any] = {
            'bufferView': self.add_view(data, target),
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

    def add_floats(self, array: np.ndarray, kind: str, bounds: bool = False) -> int:
        return self.add_accessor(np.asarray(array, '<f4'), kind, FLOAT,
                                 target=ARRAY_BUFFER, bounds=bounds)


class _IdentityCache:
    """Indices already assigned to objects, keyed by identity.

    The cache holds a reference to each object it has seen. ``id()`` on its own
    is not a safe key: a mesh that is collected frees its address for the next
    allocation, and an unrelated second mesh at that address would then be
    handed the first one's index and written as a copy of it.
    """

    def __init__(self) -> None:
        self._entries: dict[int, tuple[Any, int]] = {}

    def get(self, obj: Any) -> Optional[int]:
        found = self._entries.get(id(obj))
        return None if found is None else found[1]

    def set(self, obj: Any, index: int) -> int:
        self._entries[id(obj)] = (obj, index)
        return index


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

# Written when the field differs from the glTF default. Each entry is
# (extension, {json key: (material field, default)}); the reader's handler table
# in materials.py is the other half of the pair.
_MATERIAL_EXTENSIONS: tuple[tuple[str, dict[str, tuple[str, Any]]], ...] = (
    ('KHR_materials_unlit', {}),
    # Ours: the vertex colours on this material are light worked out when the
    # world was built rather than a tint on the surface, so a reader adds them
    # as emission and lets its own lights shade the surface underneath.
    ('OGLC_materials_baked_light', {}),
    ('KHR_materials_emissive_strength',
     {'emissiveStrength': ('emissiveStrength', 1.0)}),
    ('KHR_materials_ior', {'ior': ('ior', 1.5)}),
    ('KHR_materials_specular', {'specularFactor': ('specular', 1.0),
                                'specularColorFactor': ('specularColor', (1.0, 1.0, 1.0))}),
    ('KHR_materials_clearcoat', {'clearcoatFactor': ('clearcoat', 0.0),
                                 'clearcoatRoughnessFactor': ('clearcoatRoughness', 0.0)}),
    ('KHR_materials_sheen', {'sheenColorFactor': ('sheenColor', (0.0, 0.0, 0.0)),
                             'sheenRoughnessFactor': ('sheenRoughness', 0.0)}),
    ('KHR_materials_transmission', {'transmissionFactor': ('transmission', 0.0)}),
    ('KHR_materials_volume', {'thicknessFactor': ('thickness', 0.0),
                              'attenuationColor': ('attenuationColor', (1.0, 1.0, 1.0)),
                              'attenuationDistance': ('attenuationDistance', 0.0)}),
    ('KHR_materials_diffuse_transmission',
     {'diffuseTransmissionFactor': ('diffuseTransmission', 0.0),
      'diffuseTransmissionColorFactor': ('diffuseTransmissionColor', (1.0, 1.0, 1.0))}),
    ('KHR_materials_anisotropy', {'anisotropyStrength': ('anisotropyStrength', 0.0),
                                  'anisotropyRotation': ('anisotropyRotation', 0.0)}),
    ('KHR_materials_dispersion', {'dispersion': ('dispersion', 0.0)}),
    ('KHR_materials_iridescence',
     {'iridescenceFactor': ('iridescence', 0.0),
      'iridescenceIor': ('iridescenceIor', 1.3),
      'iridescenceThicknessMinimum': ('iridescenceThicknessMin', 100.0),
      'iridescenceThicknessMaximum': ('iridescenceThicknessMax', 400.0)}),
)

# attenuationDistance is +inf in glTF and 0.0 in PBRMaterial ("no absorption"),
# so the sentinel must not be written as a literal distance of zero.
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
}

# The textureInfo key each extension gives its channel.
_EXTENSION_TEXTURE_KEY = {
    'specular': 'specularTexture', 'specularColor': 'specularColorTexture',
    'clearcoat': 'clearcoatTexture', 'clearcoatRoughness': 'clearcoatRoughnessTexture',
    'clearcoatNormal': 'clearcoatNormalTexture',
    'sheenColor': 'sheenColorTexture', 'sheenRoughness': 'sheenRoughnessTexture',
    'transmission': 'transmissionTexture', 'thickness': 'thicknessTexture',
    'iridescence': 'iridescenceTexture',
    'iridescenceThickness': 'iridescenceThicknessTexture',
    'anisotropy': 'anisotropyTexture',
    'diffuseTransmission': 'diffuseTransmissionTexture',
    'diffuseTransmissionColor': 'diffuseTransmissionColorTexture',
}

# Bit per channel in PBRMaterial.texCoordMask: set means "sample TEXCOORD_1".
_TEXCOORD_BIT = {'baseColor': 1, 'metallicRoughness': 2, 'normal': 4,
                 'occlusion': 8, 'emissive': 16}


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

class GLTFWriter:
    """Builds a glTF 2.0 document and serializes it as GLB.

    Add meshes and nodes in any order -- ``add_mesh`` and ``add_node`` return the
    index the document gives each one -- then call :meth:`to_glb` for the bytes or
    :meth:`write` to put them on disk. Meshes and materials passed twice are
    written once and referenced twice, so a scatter of a thousand identical props
    costs one mesh.

    Nodes added with no parent become roots of the default scene.
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
        self._mesh_index = _IdentityCache()
        self._material_index = _IdentityCache()
        self._image_index = _IdentityCache()
        self._texture_index: dict[tuple, int] = {}

    # -- meshes ----------------------------------------------------------------

    def add_mesh(self, mesh: Union[PBRMesh, Sequence[PBRMesh]],
                 name: Optional[str] = None) -> int:
        """Write one mesh (or a group of primitives) and return its index.

        Passing the same :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` object
        again returns the index already assigned to it.
        """
        primitives_source = [mesh] if isinstance(mesh, PBRMesh) else list(mesh)
        if len(primitives_source) == 1:
            cached = self._mesh_index.get(primitives_source[0])
            if cached is not None:
                return cached
        entry: dict[str, Any] = {
            'primitives': [self._primitive(m) for m in primitives_source]}
        if name:
            entry['name'] = name
        self._meshes.append(entry)
        index = len(self._meshes) - 1
        if len(primitives_source) == 1:
            self._mesh_index.set(primitives_source[0], index)
        return index

    def _primitive(self, mesh: PBRMesh) -> dict:
        positions = np.asarray(mesh.positions, '<f4')
        if positions.ndim != 2 or positions.shape[1] != 3 or not len(positions):
            raise ValueError("a glTF primitive needs a non-empty (N,3) POSITION array")
        count = len(positions)
        attributes = {'POSITION': self._buffer.add_floats(positions, 'VEC3', bounds=True)}

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
                array, _kind_for(array, name, allowed))

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
                target=ELEMENT_ARRAY_BUFFER)
        mode = int(getattr(mesh, 'draw_mode', 4) or 0)
        if mode != 4:                                    # TRIANGLES is the default
            primitive['mode'] = mode
        material = getattr(mesh, 'material', None)
        if material is not None:
            primitive['material'] = self.add_material(material)
        return primitive

    # -- materials -------------------------------------------------------------

    def add_material(self, material: Any, name: Optional[str] = None) -> int:
        """Write a :class:`~OpenGLContext.scenegraph.pbrmaterial.PBRMaterial`.

        Returns the index; the same material object passed again reuses it.
        Without a ``name``, the material's own ``DEF`` is written as the glTF
        material name, so a material a caller can address by name in one
        document is addressable by that name in the document written from it.
        """
        cached = self._material_index.get(material)
        if cached is not None:
            return cached
        entry = self._material_json(material, name or getattr(material, 'DEF', '') or None)
        self._materials.append(entry)
        return self._material_index.set(material, len(self._materials) - 1)

    def _material_json(self, material: Any, name: Optional[str]) -> dict:
        textures = dict(getattr(material, 'textures', None) or {})
        mask = int(getattr(material, 'texCoordMask', 0) or 0)

        def texture_info(channel: str, srgb: bool) -> Optional[dict]:
            holder = textures.get(channel)
            if holder is None:
                return None
            info: dict[str, Any] = {'index': self._add_texture(holder, srgb)}
            if mask & _TEXCOORD_BIT.get(channel, 0):
                info['texCoord'] = 1
            transform = self._texture_transform(material, channel, mask)
            if transform is not None:
                info['extensions'] = {'KHR_texture_transform': transform}
                self._extensions_used.add('KHR_texture_transform')
            return info

        alpha_mode = str(getattr(material, 'alphaMode', 'OPAQUE') or 'OPAQUE')
        alpha = (1.0 - float(getattr(material, 'transparency', 0.0))
                 if alpha_mode == 'BLEND' else 1.0)
        pbr: dict[str, Any] = {
            'baseColorFactor': [float(c) for c in material.baseColor] + [alpha],
            'metallicFactor': float(material.metallic),
            'roughnessFactor': float(material.roughness),
        }
        base_color = texture_info('baseColor', srgb=True)
        if base_color is not None:
            pbr['baseColorTexture'] = base_color
        metallic_roughness = texture_info('metallicRoughness', srgb=False)
        if metallic_roughness is not None:
            pbr['metallicRoughnessTexture'] = metallic_roughness

        entry: dict[str, Any] = {'pbrMetallicRoughness': pbr}
        if name:
            entry['name'] = name
        emissive = [float(c) for c in getattr(material, 'emissiveColor', (0, 0, 0))]
        if any(abs(c) > 1e-6 for c in emissive):
            entry['emissiveFactor'] = emissive
        if alpha_mode != 'OPAQUE':
            entry['alphaMode'] = alpha_mode
        if alpha_mode == 'MASK':
            entry['alphaCutoff'] = float(getattr(material, 'alphaCutoff', 0.5))
        if bool(getattr(material, 'doubleSided', False)):
            entry['doubleSided'] = True

        normal = texture_info('normal', srgb=False)
        if normal is not None:
            scale = float(getattr(material, 'normalScale', 1.0))
            entry['normalTexture'] = dict(normal, scale=scale) if scale != 1.0 else normal
        occlusion = texture_info('occlusion', srgb=False)
        if occlusion is not None:
            strength = float(getattr(material, 'occlusionStrength', 1.0))
            entry['occlusionTexture'] = (dict(occlusion, strength=strength)
                                         if strength != 1.0 else occlusion)
        emissive_texture = texture_info('emissive', srgb=True)
        if emissive_texture is not None:
            entry['emissiveTexture'] = emissive_texture

        extensions = self._material_extensions(material, texture_info)
        if extensions:
            entry['extensions'] = extensions
            self._extensions_used.update(extensions)
        return entry

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
                if attribute in _SENTINEL_INFINITY and _close(value, 0.0):
                    continue
                if not _close(value, default):
                    block[key] = _factor(value)
            if extension == 'KHR_materials_unlit':
                if bool(getattr(material, 'unlit', False)):
                    wanted[extension] = {}
                continue
            if extension == 'OGLC_materials_baked_light':
                if bool(getattr(material, 'bakedLight', False)):
                    wanted[extension] = {}
                continue
            if block or extension in wanted:
                wanted.setdefault(extension, {}).update(block)
        for channel, key in _EXTENSION_TEXTURE_KEY.items():
            extension = _MATERIAL_TEXTURE_EXTENSION.get(channel)
            if extension in wanted and channel in textures:
                srgb = channel in ('specularColor', 'sheenColor',
                                   'diffuseTransmissionColor')
                info = texture_info(channel, srgb)
                if info is not None:
                    wanted[extension][key] = info
        return wanted

    @staticmethod
    def _texture_transform(material: Any, channel: str, mask: int) -> Optional[dict]:
        """``KHR_texture_transform`` for a channel the material transforms.

        The loader records the parsed offset/rotation/scale on the material and
        marks the channels it applies to in the high bits of ``texCoordMask``, so
        a document that transformed one map round-trips as one transformed map.
        """
        params = getattr(material, '_uv_params', None)
        if not params or not (mask & (_TEXCOORD_BIT.get(channel, 0) << 8)):
            return None
        transform = {'offset': [float(v) for v in params.get('offset', (0, 0))],
                     'rotation': float(params.get('rotation', 0.0)),
                     'scale': [float(v) for v in params.get('scale', (1, 1))]}
        if mask & _TEXCOORD_BIT.get(channel, 0):
            transform['texCoord'] = 1
        return transform

    # -- textures --------------------------------------------------------------

    def _add_texture(self, holder: Any, srgb: bool) -> int:
        sampler = self._add_sampler(holder)
        image = self._add_image(holder)
        key = (image, sampler)
        cached = self._texture_index.get(key)
        if cached is not None:
            return cached
        entry: dict[str, Any] = {'source': image}
        if sampler is not None:
            entry['sampler'] = sampler
        self._textures.append(entry)
        index = len(self._textures) - 1
        self._texture_index[key] = index
        return index

    def _add_image(self, holder: Any) -> int:
        """Embed a holder's pixels as a bufferView, PIL images encoded as PNG."""
        if isinstance(holder, ExternalImage):
            cached = self._image_index.get(holder)
            if cached is not None:
                return cached
            self._images.append({'uri': holder.uri})
            return self._image_index.set(holder, len(self._images) - 1)
        if isinstance(holder, EncodedImage):
            cached = self._image_index.get(holder)
            if cached is not None:
                return cached
            view = self._buffer.add_view(holder.data)
            self._images.append({'bufferView': view, 'mimeType': holder.mime_type})
            return self._image_index.set(holder, len(self._images) - 1)
        image = holder.image
        cached = self._image_index.get(image)
        if cached is not None:
            return cached
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        view = self._buffer.add_view(buffer.getvalue())
        self._images.append({'bufferView': view, 'mimeType': 'image/png'})
        return self._image_index.set(image, len(self._images) - 1)

    def _add_sampler(self, holder: Any) -> Optional[int]:
        """The sampler for a holder's wrap/filter enums, or None for defaults."""
        entry = {key: int(value) for key, value in (
            ('wrapS', getattr(holder, 'wrap_s', None)),
            ('wrapT', getattr(holder, 'wrap_t', None)),
            ('minFilter', getattr(holder, 'min_filter', None)),
            ('magFilter', getattr(holder, 'mag_filter', None)),
        ) if value}
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
            entry['mesh'] = self.add_mesh(node.mesh)
        if node.instances is not None:
            entry.setdefault('extensions', {})['EXT_mesh_gpu_instancing'] = \
                self._instancing(node.instances)
            self._extensions_used.add('EXT_mesh_gpu_instancing')
        if node.children:
            entry['children'] = [self.add_node(child, root=False)
                                 for child in node.children]
        self._nodes.append(entry)
        index = len(self._nodes) - 1
        if root:
            self._roots.append(index)
        return index

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
        for key, value in (('nodes', self._nodes), ('meshes', self._meshes),
                           ('materials', self._materials), ('textures', self._textures),
                           ('images', self._images), ('samplers', self._samplers),
                           ('accessors', self._buffer.accessors),
                           ('bufferViews', self._buffer.views)):
            if value:
                doc[key] = value
        if self._buffer.blob:
            doc['buffers'] = [{'byteLength': len(self._buffer.blob)}]
        if self._extensions_used:
            doc['extensionsUsed'] = sorted(self._extensions_used)
        return doc

    def to_glb(self) -> bytes:
        """The document as binary glTF."""
        return _pack_glb(self.document(), bytes(self._buffer.blob))

    def write(self, path: str) -> bytes:
        """Write the document to ``path`` and return the bytes written."""
        data = self.to_glb()
        with open(path, 'wb') as handle:
            handle.write(data)
        return data


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


def write_glb(content: Union[MeshLike, Iterable[MeshLike]],
              path: Optional[str] = None, generator: str = GENERATOR) -> bytes:
    """Write meshes or nodes as a ``.glb`` and return the bytes.

    ``content`` is a :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh`, a
    :class:`SceneNode`, or any iterable of them; a bare mesh is placed at the
    origin. With ``path``, the bytes are also written there.
    """
    items = ([content] if isinstance(content, (PBRMesh, SceneNode))
             else list(content))
    writer = GLTFWriter(generator=generator)
    for item in items:
        writer.add_node(item if isinstance(item, SceneNode) else SceneNode(mesh=item))
    if path is not None:
        return writer.write(path)
    return writer.to_glb()
