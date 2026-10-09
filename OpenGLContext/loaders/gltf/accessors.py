"""glTF accessor decoding: buffers, bufferViews and accessors -> numpy arrays.

The bottom layer of the loader. Every vertex attribute, index buffer, animation
sampler and inverse-bind matrix in a glTF reaches numpy through here. It handles
the three storage forms the spec allows -- dense bufferView data (including
interleaved ``byteStride`` views), sparse accessors (index/value overrides on a
base array), and normalized integers (dequantized to float per the spec) -- and
validates declared sizes against the real buffer, so a malformed asset raises a
located error instead of reading past the end of a numpy view.

Raw bytes come from the security-hardened :mod:`resolver` (external URIs, ``data:``
URIs, GLB blobs); decoded buffers are memoised on the resolver by index, so a file
whose accessors share one buffer decodes it once.
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from OpenGLContext.loaders.documentvalues import bounded
from OpenGLContext.loaders.gltf import meshopt
from OpenGLContext.loaders.resolver import Resolver, decode_data_uri, resolver_max

if TYPE_CHECKING:
    import pygltflib

log = logging.getLogger(__name__)


# glTF accessor componentType enums (== GL type enums)
_COMPONENT_FLOAT = 5126        # GL_FLOAT
_COMPONENT_HALF = 5131         # GL_HALF_FLOAT, KHR_accessor_float16
_COMPONENT_DOUBLE = 5130       # GL_DOUBLE, KHR_accessor_float64
_COMPONENT_DTYPE = {
    5120: np.int8, 5121: np.uint8, 5122: np.int16,
    5123: np.uint16, 5125: np.uint32, _COMPONENT_FLOAT: np.float32,
    _COMPONENT_HALF: np.float16, _COMPONENT_DOUBLE: np.float64,
}
#: The floating-point component types. An accessor of one of these is never
#: dequantized, whatever its ``normalized`` flag says: both extensions forbid
#: the flag on them.
FLOAT_COMPONENTS = frozenset((_COMPONENT_HALF, _COMPONENT_FLOAT, _COMPONENT_DOUBLE))
_TYPE_COUNT = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4,
               'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


def _component_dtype(component_type: int) -> type:
    """numpy dtype for an accessor componentType, or a located ValueError."""
    try:
        return _COMPONENT_DTYPE[component_type]
    except KeyError as err:
        raise ValueError(
            "glTF accessor has unknown componentType %r (expected one of %s)"
            % (component_type, sorted(_COMPONENT_DTYPE))) from err


def _type_count(accessor_type: str) -> int:
    """Component count for an accessor ``type``, or a located ValueError."""
    try:
        return _TYPE_COUNT[accessor_type]
    except KeyError as err:
        raise ValueError(
            "glTF accessor has unknown type %r (expected one of %s)"
            % (accessor_type, sorted(_TYPE_COUNT))) from err


def _buffer_bytes(g: "pygltflib.GLTF2", buffer_index: int, resolver: Resolver) -> bytes:
    """Return the decoded bytes of buffer ``buffer_index`` (decoded once, cached).

    Several accessors commonly share one data-URI or GLB binary blob, so the
    resolver memoises the decoded bytes by buffer index and each buffer is
    base64-decoded or fetched once however many accessors read from it.
    """
    cache: Optional[dict[int, bytes]] = (
        getattr(resolver, '_buffers', None) if resolver is not None else None
    )
    if cache is not None and buffer_index in cache:
        return cache[buffer_index]
    buf = g.buffers[buffer_index]
    uri = getattr(buf, 'uri', None)
    data: bytes
    if uri is None and meshopt.is_fallback_buffer(buf):
        # Only meshopt views refer to it, and they decode from elsewhere; in a
        # GLB, reading it as the binary chunk would hand back the wrong bytes.
        raise ValueError("glTF buffer %d is a meshopt fallback with no data of "
                         "its own" % (buffer_index,))
    if uri is None:
        data = g.binary_blob()
    elif uri.startswith('data:'):
        data = decode_data_uri(uri, resolver_max(resolver))
    else:
        data = resolver.fetch(uri)
    if cache is not None:
        cache[buffer_index] = data
    return data


def view_bytes(g: "pygltflib.GLTF2", view_index: int, resolver: Resolver) -> memoryview:
    """The bytes of buffer view ``view_index``, exactly its ``byteLength``.

    A view carrying ``KHR_meshopt_compression`` or ``EXT_meshopt_compression``
    is decompressed from the buffer its extension names (:mod:`meshopt`), once
    per resolver; its own ``buffer`` is then a stand-in that is never read.
    Every other view is a window on its buffer, checked to lie inside it.
    """
    views = g.bufferViews or []
    if not 0 <= view_index < len(views):
        raise ValueError("glTF bufferView %d does not exist" % (view_index,))
    view = views[view_index]
    extension = meshopt.view_extension(view)
    if extension is None:
        data = _buffer_bytes(g, view.buffer, resolver)
        return _window(data, view.byteOffset or 0, view.byteLength,
                       "bufferView %d" % (view_index,))
    cache: Optional[dict[int, bytes]] = getattr(resolver, '_views', None)
    if cache is None:                  # a stand-in resolver: decode on each read
        cache = {}
    if view_index not in cache:
        source = extension.get('buffer')
        if not isinstance(source, int) or not 0 <= source < len(g.buffers or []):
            raise ValueError("glTF bufferView %d's meshopt data names buffer %r"
                             % (view_index, source))
        compressed = _window(_buffer_bytes(g, source, resolver),
                             extension.get('byteOffset', 0) or 0,
                             extension.get('byteLength'),
                             "bufferView %d's meshopt data" % (view_index,))
        try:
            cache[view_index] = meshopt.decode_view(extension, bytes(compressed),
                                                    view.byteLength)
        except meshopt.MeshoptError as err:
            raise ValueError("glTF bufferView %d: %s" % (view_index, err)) from err
    return memoryview(cache[view_index])


def _window(data: bytes, offset: int, length: Optional[int], what: str) -> memoryview:
    """``length`` bytes of ``data`` from ``offset``, or a located error."""
    if not isinstance(offset, int) or offset < 0 or offset > len(data):
        raise ValueError("glTF %s starts at %r, outside its %d-byte buffer"
                         % (what, offset, len(data)))
    if length is None:
        length = len(data) - offset
    if not isinstance(length, int) or length < 0 or offset + length > len(data):
        raise ValueError("glTF %s reads %r bytes at offset %d but its buffer holds "
                         "only %d" % (what, length, offset, len(data)))
    return memoryview(data)[offset:offset + length]


def _accessor_base(g: "pygltflib.GLTF2", acc: "pygltflib.Accessor", resolver: Resolver,
                   index: Optional[int] = None) -> np.ndarray:
    """Decode the (dense) buffer-view data of an accessor as an (count, ncomp) array.

    Handles interleaved (``byteStride``) accessors with a strided view rather than a
    per-vertex Python loop. Returns zeros when the accessor has no bufferView (a
    sparse accessor whose base is implicitly all-zero); the caller applies sparse
    substitution on top. The declared ``count`` and ``byteStride`` are validated
    against the real buffer length so a malformed asset raises a located error
    instead of an opaque numpy read past the end.
    """
    dtype = np.dtype(_component_dtype(acc.componentType))
    ncomp = _type_count(acc.type)
    count = _checked_count(acc.count, _acc_label(index))
    if acc.bufferView is None:
        return np.zeros((count, ncomp), dtype=dtype)
    bv = g.bufferViews[acc.bufferView]
    data = view_bytes(g, acc.bufferView, resolver)
    offset = acc.byteOffset or 0
    item = dtype.itemsize * ncomp
    stride = bv.byteStride or item
    # A stride that is negative, zero, or does not divide the component size
    # makes the strided window below walk outside the bytes it was built from --
    # ``as_strided`` does no bounds checking of its own. glTF requires a positive
    # byteStride that is a multiple of 4, so every conformant asset passes.
    if stride <= 0 or stride % dtype.itemsize:
        raise ValueError(
            "glTF %s has an invalid byteStride %d for its %d-byte "
            "component" % (_acc_label(index), stride, dtype.itemsize))
    span = (count - 1) * stride + item if count else 0
    if offset < 0 or offset + span > len(data):
        raise ValueError(
            "glTF %s reads %d bytes at offset %d but its buffer view holds "
            "only %d" % (_acc_label(index), span, offset, len(data)))
    if stride == item:
        flat = np.frombuffer(data, dtype=dtype, count=count * ncomp, offset=offset)
        return flat.reshape(count, ncomp)
    # Interleaved: read each component with a strided view (no per-vertex loop).
    # The stride divides the component size, so ``span`` is a whole number of
    # components and the window covers exactly the bytes as_strided walks.
    window = np.frombuffer(data, dtype=dtype, count=span // dtype.itemsize, offset=offset)
    strided = np.lib.stride_tricks.as_strided(
        window, shape=(count, ncomp), strides=(stride, dtype.itemsize))
    return np.ascontiguousarray(strided)


def _acc_label(index: Optional[int]) -> str:
    return "accessor %s" % ('?' if index is None else index)


def _checked_count(count: Any, what: str) -> int:
    """A declared element count, refusing a negative one.

    ``np.frombuffer`` reads *the whole remaining buffer* for any negative
    ``count`` rather than raising, so a negative count from a file silently
    widens every read that derives its length from it.
    """
    n = int(count)
    if n < 0:
        raise ValueError("glTF %s declares a negative count (%d)" % (what, n))
    return n


def declared_bounds(acc: Any) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """A ``POSITION`` accessor's declared ``min`` and ``max``, or None.

    None where the accessor declares either one as anything other than at
    least three finite numbers; the caller then measures the points instead.
    """
    corners = []
    for declared in (getattr(acc, 'min', None), getattr(acc, 'max', None)):
        if not isinstance(declared, (list, tuple)) or len(declared) < 3:
            return None
        corner = np.array([bounded(value, math.nan) for value in declared[:3]], 'd')
        if not np.all(np.isfinite(corner)):
            return None
        if getattr(acc, 'normalized', False) and \
                getattr(acc, 'componentType', None) in _COMPONENT_DTYPE and \
                acc.componentType not in FLOAT_COMPONENTS:
            # KHR_mesh_quantization: min/max are in the accessor's integers,
            # and the vertices are read normalized.
            corner = _normalize_array(
                corner.astype(_COMPONENT_DTYPE[acc.componentType])).astype('d')
        corners.append(corner)
    return corners[0], corners[1]


def _shared(resolver: Resolver, kind: str, index: int) -> Optional[np.ndarray]:
    """The array already decoded for ``(kind, index)``, if this resolver shares.

    A resolver built for one load has no share map, so a single load decodes each
    accessor as it always did. A resolver pointed at a
    :class:`~OpenGLContext.loaders.gltf.loader.SharedDocument`'s map returns the
    array an earlier build already decoded -- the immutable vertex and keyframe
    data every instance of one asset holds in common.
    """
    cache = getattr(resolver, 'shared_reads', None)
    return None if cache is None else cache.get((kind, index))


def _keep(resolver: Resolver, kind: str, index: int, arr: np.ndarray) -> np.ndarray:
    """Offer ``arr`` to the resolver's share map and return it (read-only there).

    Shared arrays are marked non-writeable so a consumer that deforms a mesh does
    it on its own copy (the deform already reads the base through ``astype``); an
    in-place write to shared vertex data would move every instance at once.
    """
    cache = getattr(resolver, 'shared_reads', None)
    if cache is not None:
        arr.flags.writeable = False
        cache[(kind, index)] = arr
    return arr


def _read_accessor(g: "pygltflib.GLTF2", index: int, resolver: Resolver) -> np.ndarray:
    shared = _shared(resolver, 'accessor', index)
    if shared is not None:
        return shared
    acc = g.accessors[index]
    dtype = np.dtype(_component_dtype(acc.componentType))
    ncomp = _type_count(acc.type)
    sparse = getattr(acc, 'sparse', None)
    if acc.bufferView is None and sparse is None:
        # Never fabricate silent zeros -- a caller reading this would render
        # origin-collapsed geometry with no indication anything was dropped.
        raise NotImplementedError(
            "glTF accessor %d has no bufferView and no sparse data" % index)
    arr = _accessor_base(g, acc, resolver, index)
    if sparse is not None:
        arr = _apply_sparse(g, acc, sparse, arr, dtype, ncomp, resolver)
    return _keep(resolver, 'accessor', index, arr)


def _apply_sparse(g: "pygltflib.GLTF2", acc: "pygltflib.Accessor", sparse: "pygltflib.Sparse",
                  base: np.ndarray, dtype: np.dtype, ncomp: int,
                  resolver: Resolver) -> np.ndarray:
    """Scatter a sparse accessor's index->value overrides onto the base array."""
    n = _checked_count(sparse.count, "sparse accessor")
    si, sv = sparse.indices, sparse.values
    idx_dtype = np.dtype(_component_dtype(si.componentType))
    idata = view_bytes(g, si.bufferView, resolver)
    ioff = getattr(si, 'byteOffset', 0) or 0
    indices = np.frombuffer(idata, dtype=idx_dtype, count=n, offset=ioff)
    vdata = view_bytes(g, sv.bufferView, resolver)
    voff = getattr(sv, 'byteOffset', 0) or 0
    values = np.frombuffer(vdata, dtype=dtype, count=n * ncomp, offset=voff).reshape(n, ncomp)
    out = np.array(base, dtype=dtype)   # writable copy (frombuffer views are read-only)
    out[np.asarray(indices, dtype=np.intp)] = values
    return out


def _normalize_component(value: np.integer) -> float:
    """glTF normalized-integer -> float. Unsigned maps [0,MAX]->[0,1]; signed maps
    [-MAX,MAX]->[-1,1] with the extra negative code (e.g. int8 -128) clamped to -1."""
    info = np.iinfo(value.dtype)
    if info.min < 0:
        return max(float(value) / float(info.max), -1.0)
    return float(value) / float(info.max)


def _normalize_array(arr: np.ndarray, dtype: Optional[Any] = None) -> np.ndarray:
    """Vectorised :func:`_normalize_component` for a whole integer array.

    ``dtype`` selects the integer type whose range sets the divisor and the
    signed clamp, defaulting to the array's own dtype. The Draco path passes the
    accessor's declared componentType so a stream that decodes to floats is still
    normalized by the authored integer range rather than its runtime dtype.
    """
    info = np.iinfo(dtype if dtype is not None else arr.dtype)
    out = arr.astype(np.float32) / float(info.max)
    if info.min < 0:
        np.maximum(out, -1.0, out=out)
    return out


def _read_floats(g: "pygltflib.GLTF2", index: int, resolver: Resolver,
                 precise: bool = False) -> np.ndarray:
    """Read an accessor as floats, honouring ``accessor.normalized``.

    Float accessors of any width pass through; integer accessors are divided by
    their type maximum only when flagged ``normalized`` (signed clamped to -1),
    as ``KHR_mesh_quantization`` and the core specification say, and are
    otherwise read as the integers they hold.

    The result is float32, what a vertex buffer holds. ``precise`` returns
    float64 instead, for animation keyframes, which ``KHR_accessor_float64``
    requires to be interpolated in double precision; a double accessor read
    without it is logged, since its values are rounded to single precision.
    """
    kind = 'precise' if precise else 'floats'
    shared = _shared(resolver, kind, index)
    if shared is not None:
        return shared
    acc = g.accessors[index]
    arr = _read_accessor(g, index, resolver)
    out = _coerce_normalized(acc, arr, np.float64 if precise else np.float32)
    if not precise and acc.componentType == _COMPONENT_DOUBLE:
        log.warning("glTF %s holds double-precision values; they are drawn in "
                    "single precision", _acc_label(index))
    return _keep(resolver, kind, index, out)


def _read_normalized(g: "pygltflib.GLTF2", index: int, resolver: Resolver) -> np.ndarray:
    """:func:`_read_floats` as float32, the form every vertex attribute takes."""
    return _read_floats(g, index, resolver)


def _coerce_normalized(acc: "pygltflib.Accessor", arr: np.ndarray,
                       dtype: Any = np.float32) -> np.ndarray:
    """Apply :func:`_read_floats`'s policy to an already-decoded array.

    The Draco path yields attribute values without the accessor's bufferView, but
    the accessor is still authoritative for componentType/normalized. Float
    accessors pass through; a ``normalized`` integer accessor divides by its
    declared componentType's maximum (signed clamped to -1) -- the divisor comes
    from the accessor, not the decoded array's dtype, so a Draco stream that hands
    back floats is normalized the same as one that hands back integers.
    """
    if acc.componentType not in FLOAT_COMPONENTS and getattr(acc, 'normalized', False):
        arr = _normalize_array(arr, _component_dtype(acc.componentType))
    # A copy: the decoded array may be a read-only view of the buffer, and the
    # caller owns what it is handed.
    return np.array(arr, dtype=dtype, order='C')


def _colors_to_rgba(arr: np.ndarray) -> np.ndarray:
    """Pad a VEC3 colour array to RGBA (VEC4 passes through)."""
    if arr.shape[1] == 3:
        arr = np.concatenate([arr, np.ones((arr.shape[0], 1), np.float32)], axis=1)
    return np.ascontiguousarray(arr)


def _read_texcoords(g: "pygltflib.GLTF2", index: int, resolver: Resolver) -> np.ndarray:
    return _read_normalized(g, index, resolver)


def _read_colors(g: "pygltflib.GLTF2", index: int, resolver: Resolver) -> np.ndarray:
    """Read a COLOR_0 accessor (VEC3/VEC4, float or normalized int) as RGBA float32."""
    return _colors_to_rgba(_read_normalized(g, index, resolver))
