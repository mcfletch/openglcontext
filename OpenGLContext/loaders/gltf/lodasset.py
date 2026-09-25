"""A level-of-detail chain in a ``.glb``, read one level at a time.

:func:`~OpenGLContext.loaders.gltf.load_gltf` builds every level of an
``MSFT_lod`` chain into the scene at once. A tool or a streaming reader that
wants one level -- the coarsest to draw straight away, a finer one when the
object comes close -- opens the file with :class:`LODAsset` instead:
:meth:`LODAsset.open` parses the JSON chunk and nothing else, and
:meth:`LODAsset.load` reads the byte ranges one level's accessors name.

    from OpenGLContext.loaders.gltf.lodasset import LODAsset

    asset = LODAsset.open('bust.glb')       # parses kilobytes of JSON
    asset.levels[-1].triangle_count         # described without reading it
    attributes, indices = asset.load(len(asset.levels) - 1)

A chain written by :meth:`~OpenGLContext.loaders.gltf.writer.GLTFWriter.add_lod`
with a ``buffer`` per finer level keeps the coarsest in the glB's own binary
chunk and each finer level in a file beside it, so a level that is never asked
for is never opened. Every ``uri`` is data from the file and goes through
:class:`~OpenGLContext.loaders.resolver.Resolver`: a level's file must be under
the directory the ``.glb`` is in, and how many bytes one accessor may ask for is
bounded by ``max_resource_bytes``.

The chain is the scene's first root node carrying ``MSFT_lod``, or the first
root node where none does (a chain of one level). Each level is one mesh of
one indexed or unindexed triangle primitive, stored densely or interleaved, in
any component type glTF allows, with ``normalized`` integers scaled to floats.
A sparse accessor is refused rather than read, since its bytes are elsewhere
in the file.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from OpenGLContext.loaders.documentvalues import (
    DocumentValues, JSONObject, parse_object, require_array, require_index,
    require_item, require_object, require_text, require_whole,
)
from OpenGLContext.loaders.gltf import lod as _lod
from OpenGLContext.loaders.gltf.accessors import (
    _checked_count,
    _component_dtype,
    _normalize_array,
    _type_count,
)
from OpenGLContext.loaders.resolver import (
    DEFAULT_MAX_RESOURCE_BYTES,
    Resolver,
    check_size,
    contained_source,
    decode_data_uri,
)

__all__ = ['LODAsset', 'LODEntry', 'LOD_ERROR']

#: The document ``extras`` key a baked chain states each level's geometric
#: error in, finest first, in the model's own units.
LOD_ERROR = 'OPENGLCONTEXT_lod_error'

_GLB_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_TRIANGLES = 4


@dataclass(frozen=True)
class LODEntry:
    """One level, as the file describes it before anything is read.

    Everything here comes from the JSON chunk, so a caller can decide which
    level it wants -- and what that will cost -- without touching the geometry.
    """

    level: int
    triangle_count: int
    vertex_count: int
    #: The level's geometric error in the model's units, from
    #: :data:`LOD_ERROR`; 0.0 where the file states none.
    error: float
    #: Share of the window's height at or above which this level is the one to
    #: draw, as ``MSFT_screencoverage`` states it or the loader would guess it.
    screen_coverage: float
    #: Where the bytes are: the file's name, or None for the glb's own chunk.
    source: Optional[str]
    byte_length: int


class LODAsset:
    """A baked chain, opened without reading its geometry.

    ``levels`` describes each level, finest first; :meth:`load` reads one.
    """

    def __init__(self, path: str, document: JSONObject, binary_offset: int,
                 max_resource_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES
                 ) -> None:
        self.path = contained_source(path)
        self.document = document
        self._binary_offset = binary_offset
        self.max_resource_bytes = max_resource_bytes
        #: Confines every ``uri`` in the document to the glb's own directory.
        self.resolver = Resolver(
            base_dir=os.path.dirname(os.path.abspath(path)) or '.',
            max_resource_bytes=max_resource_bytes)
        self._root = _chain_root(document)
        self._meshes = _level_meshes(document, self._root)
        self.levels = tuple(self._describe())

    @classmethod
    def open(cls, path: str,
             max_resource_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES
             ) -> 'LODAsset':
        """The chain in the ``.glb`` at ``path``, having read its JSON chunk
        and nothing else."""
        path = contained_source(path)
        with open(path, 'rb') as handle:
            header = handle.read(12)
            if len(header) != 12 or struct.unpack('<I', header[:4])[0] != _GLB_MAGIC:
                raise ValueError('%r is not a glb' % (path,))
            json_length, json_kind = struct.unpack('<II', handle.read(8))
            if json_kind != _JSON_CHUNK:
                raise ValueError('%r does not begin with a JSON chunk' % (path,))
            document = parse_object(handle.read(json_length), '%r glTF JSON' % (path,))
            binary_offset = 12 + 8 + json_length
            chunk = handle.read(8)
            if len(chunk) == 8 and struct.unpack('<II', chunk)[1] == _BIN_CHUNK:
                binary_offset += 8
        return cls(path, document, binary_offset, max_resource_bytes)

    def load(self, level: int) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """``(attributes, indices)`` for one level: each vertex attribute by
        its glTF name as float32 (integer attributes flagged ``normalized``
        scaled into [0, 1] or [-1, 1]), and the triangle indices as uint32.

        Only the byte ranges this level's accessors name are read. A file
        holding a finer level is opened here and nowhere else.
        """
        primitive = self._primitive(level)
        attributes = {name: self._read(require_index(raw, 'attribute %s' % (name,)))
                      .astype(np.float32, copy=False)
                      for name, raw in _attributes(primitive).items()}
        if primitive.get('indices') is None:
            indices = np.arange(len(attributes['POSITION']), dtype=np.uint32)
        else:
            indices = self._read(require_index(primitive['indices'], 'indices')
                                 ).astype(np.uint32).ravel()
        return attributes, indices

    # -- the description ------------------------------------------------------

    def _describe(self) -> list[LODEntry]:
        values = DocumentValues()
        extras = values.mapping(self.document.get('extras'), 'the document extras')
        errors = values.array(extras.get(LOD_ERROR), LOD_ERROR)
        root = require_item(self.document, 'nodes', self._root)
        coverage = _lod.screen_coverage(_Node(root.get('extras')),
                                        len(self._meshes), values)
        out = []
        for level in range(len(self._meshes)):
            primitive = self._primitive(level)
            position = self._accessor(require_index(_attributes(primitive)['POSITION'],
                                             'POSITION'))
            vertices = _checked_count(require_whole(position.get('count'), 'accessor count'),
                                      'POSITION accessor')
            drawn = (vertices if primitive.get('indices') is None else
                     _checked_count(require_whole(self._accessor(
                         require_index(primitive['indices'], 'indices')).get('count'),
                         'accessor count'), 'index accessor'))
            buffer = self._buffer_of(position)
            uri = buffer.get('uri')
            out.append(LODEntry(
                level=level, triangle_count=drawn // 3, vertex_count=vertices,
                error=(values.number(errors[level], 0.0, LOD_ERROR, minimum=0.0)
                       if level < len(errors) else 0.0),
                screen_coverage=float(coverage[level]),
                source=None if uri is None else require_text(uri, 'buffer uri'),
                byte_length=values.integer(buffer.get('byteLength'), 0,
                                           'buffer byteLength', minimum=0)))
        return out

    def _primitive(self, level: int) -> JSONObject:
        mesh = self._meshes[level]
        primitives = require_array(mesh.get('primitives') or [], 'mesh primitives')
        if len(primitives) != 1:
            raise ValueError('level %d of %r has %d primitives; a level is one'
                             % (level, self.path, len(primitives)))
        primitive = require_object(primitives[0], 'mesh primitive')
        if primitive.get('mode', _TRIANGLES) != _TRIANGLES:
            raise ValueError('level %d of %r is not a triangle list'
                             % (level, self.path))
        if 'POSITION' not in _attributes(primitive):
            raise ValueError('level %d of %r has no POSITION' % (level, self.path))
        return primitive

    def _accessor(self, index: int) -> JSONObject:
        return require_item(self.document, 'accessors', index)

    def _buffer_of(self, accessor: JSONObject) -> JSONObject:
        view = require_item(self.document, 'bufferViews',
                     require_index(accessor.get('bufferView'), 'bufferView'))
        return require_item(self.document, 'buffers',
                     require_index(view.get('buffer', 0), 'buffer'))

    # -- the bytes ------------------------------------------------------------

    def _read(self, index: int) -> np.ndarray:
        """One accessor, read from wherever its bytes are, as ``(count,
        width)`` (a scalar accessor as ``(count,)``)."""
        accessor = self._accessor(index)
        if accessor.get('sparse') is not None or accessor.get('bufferView') is None:
            raise ValueError('accessor %d of %r is sparse; a level is read from '
                             'dense accessors only' % (index, self.path))
        dtype = np.dtype(_component_dtype(
            require_whole(accessor.get('componentType'), 'componentType'))).newbyteorder('<')
        width = _type_count(require_text(accessor.get('type'), 'accessor type'))
        count = _checked_count(require_whole(accessor.get('count'), 'accessor count'),
                               'accessor %d' % (index,))
        view = require_item(self.document, 'bufferViews',
                     require_index(accessor['bufferView'], 'bufferView'))
        item = dtype.itemsize * width
        stride = require_whole(view.get('byteStride') or item, 'byteStride')
        if stride < item or stride % dtype.itemsize:
            raise ValueError('accessor %d of %r has an invalid byteStride %r'
                             % (index, self.path, stride))
        start = (require_index(view.get('byteOffset', 0), 'byteOffset')
                 + require_index(accessor.get('byteOffset', 0), 'byteOffset'))
        span = (count - 1) * stride + item if count else 0

        # What the document asks to be read, checked before anything is read:
        # a length in the JSON is a claim, not a measurement.
        check_size(span, self.max_resource_bytes, 'accessor %d' % (index,))
        raw, source = self._bytes(require_index(view.get('buffer', 0), 'buffer'), start, span)
        if len(raw) != span:
            raise ValueError('%s is short: wanted %d bytes at %d'
                             % (source, span, start))
        window = np.frombuffer(raw, dtype=np.uint8)
        rows = np.lib.stride_tricks.as_strided(
            window, shape=(count, item), strides=(stride, 1)) if count else \
            window.reshape(0, item)
        values = np.ascontiguousarray(rows).view(dtype).reshape(count, width)
        if accessor.get('normalized') and dtype.kind in 'iu':
            values = _normalize_array(values.astype(dtype.newbyteorder('=')))
        return values.reshape(count) if width == 1 else values

    def _bytes(self, buffer_index: int, start: int, length: int) -> tuple[bytes, str]:
        """``length`` bytes at ``start`` in one buffer, and where they came from."""
        raw = require_item(self.document, 'buffers', buffer_index).get('uri')
        uri = None if raw is None else require_text(raw, 'buffer uri')
        if uri is not None and uri.startswith('data:'):
            # A buffer that carries its own bytes reaches no file at all.
            whole = decode_data_uri(uri, self.max_resource_bytes)
            return whole[start:start + length], 'data: URI'
        if uri is None:
            if buffer_index != 0:
                raise ValueError('buffer %d of %r has no uri and is not the '
                                 'binary chunk' % (buffer_index, self.path))
            source, start = self.path, start + self._binary_offset
        else:
            source = self.resolver.contain(uri)
        with open(source, 'rb') as handle:
            handle.seek(start)
            return handle.read(length), source


class _Node:
    """A node's ``extras`` where :func:`~OpenGLContext.loaders.gltf.lod.screen_coverage`
    looks for them."""

    def __init__(self, extras: Any) -> None:
        self.extras = extras


def _chain_root(document: JSONObject) -> int:
    """The node that carries the chain: the scene's first root carrying
    ``MSFT_lod``, else its first root."""
    scene = (require_item(document, 'scenes', require_index(document.get('scene') or 0, 'scene'))
             if document.get('scenes') else {})
    roots = [require_index(root, 'scene node')
             for root in require_array(scene.get('nodes') or [], 'scene nodes')]
    roots = roots or list(range(len(require_array(document.get('nodes') or [],
                                                  'nodes'))))
    if not roots:
        raise ValueError('the document has no node to read a chain from')
    for index in roots:
        extensions = require_item(document, 'nodes', index).get('extensions') or {}
        if _lod.EXTENSION in require_object(extensions, 'node extensions'):
            return index
    return roots[0]


def _level_meshes(document: JSONObject, carrier: int) -> list[JSONObject]:
    """Each level's mesh, finest first, from the node carrying the chain."""
    root = require_item(document, 'nodes', carrier)
    extensions = require_object(root.get('extensions') or {}, 'node extensions')
    ids = _lod.level_ids(extensions.get(_lod.EXTENSION))
    meshes = []
    for index in [None] + ids:
        node = root if index is None else require_item(document, 'nodes', index)
        if node.get('mesh') is None:
            raise ValueError('level node %s has no mesh' % (index,))
        meshes.append(require_item(document, 'meshes', require_index(node['mesh'], 'mesh')))
    return meshes


def _attributes(primitive: JSONObject) -> JSONObject:
    return require_object(primitive.get('attributes') or {}, 'primitive attributes')
