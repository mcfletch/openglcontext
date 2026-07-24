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

from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from OpenGLContext.loaders.resolver import Resolver, _decode_data_uri, _resolver_max

if TYPE_CHECKING:
    import pygltflib


# glTF accessor componentType enums (== GL type enums)
_COMPONENT_FLOAT = 5126        # GL_FLOAT
_COMPONENT_DTYPE = {
    5120: np.int8, 5121: np.uint8, 5122: np.int16,
    5123: np.uint16, 5125: np.uint32, _COMPONENT_FLOAT: np.float32,
}
_TYPE_COUNT = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4,
               'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


def _component_dtype(component_type: int) -> type:
    """numpy dtype for an accessor componentType, or a located ValueError (5c)."""
    try:
        return _COMPONENT_DTYPE[component_type]
    except KeyError as err:
        raise ValueError(
            "glTF accessor has unknown componentType %r (expected one of %s)"
            % (component_type, sorted(_COMPONENT_DTYPE))) from err


def _type_count(accessor_type: str) -> int:
    """Component count for an accessor ``type``, or a located ValueError (5c)."""
    try:
        return _TYPE_COUNT[accessor_type]
    except KeyError as err:
        raise ValueError(
            "glTF accessor has unknown type %r (expected one of %s)"
            % (accessor_type, sorted(_TYPE_COUNT))) from err


def _buffer_bytes(g: "pygltflib.GLTF2", buffer_index: int, resolver: Resolver) -> bytes:
    """Return the decoded bytes of buffer ``buffer_index`` (decoded once, cached).

    A ``.gltf`` with several accessors sharing one data-URI or GLB binary blob was
    re-decoding (base64) / re-fetching the whole buffer on every accessor read; the
    resolver now memoises the decoded bytes by buffer index.
    """
    cache = getattr(resolver, '_buffers', None) if resolver is not None else None
    if cache is not None and buffer_index in cache:
        return cache[buffer_index]
    buf = g.buffers[buffer_index]
    uri = getattr(buf, 'uri', None)
    if uri is None:
        data = g.binary_blob()
    elif uri.startswith('data:'):
        data = _decode_data_uri(uri, _resolver_max(resolver))
    else:
        data = resolver.fetch(uri)
    if cache is not None:
        cache[buffer_index] = data
    return data


def _accessor_base(g: "pygltflib.GLTF2", acc: "pygltflib.Accessor", resolver: Resolver,
                   index: Optional[int] = None) -> np.ndarray:
    """Decode the (dense) buffer-view data of an accessor as an (count, ncomp) array.

    Handles interleaved (``byteStride``) accessors with a strided view rather than a
    per-vertex Python loop. Returns zeros when the accessor has no bufferView (a
    sparse accessor whose base is implicitly all-zero); the caller applies sparse
    substitution on top. The declared ``count``/stride is validated against the real
    buffer length so a malformed asset raises a located error instead of an opaque
    numpy read past the end.
    """
    dtype = np.dtype(_component_dtype(acc.componentType))
    ncomp = _type_count(acc.type)
    count = acc.count
    if acc.bufferView is None:
        return np.zeros((count, ncomp), dtype=dtype)
    bv = g.bufferViews[acc.bufferView]
    data = _buffer_bytes(g, bv.buffer, resolver)
    offset = (bv.byteOffset or 0) + (acc.byteOffset or 0)
    item = dtype.itemsize * ncomp
    stride = bv.byteStride or item
    span = (count - 1) * stride + item if count else 0
    if offset < 0 or offset + span > len(data):
        raise ValueError(
            "glTF accessor %s reads %d bytes at offset %d but its buffer holds "
            "only %d" % (_acc_label(index), span, offset, len(data)))
    if stride == item:
        flat = np.frombuffer(data, dtype=dtype, count=count * ncomp, offset=offset)
        return flat.reshape(count, ncomp)
    # Interleaved: read each component with a strided view (no per-vertex loop).
    # glTF aligns byteOffset and byteStride to the component size, so a dtype view
    # from ``offset`` is valid; as_strided then walks it at the vertex stride.
    span = (count - 1) * stride + item
    window = np.frombuffer(data, dtype=dtype, count=span // dtype.itemsize, offset=offset)
    strided = np.lib.stride_tricks.as_strided(
        window, shape=(count, ncomp), strides=(stride, dtype.itemsize))
    return np.ascontiguousarray(strided)


def _acc_label(index: Optional[int]) -> str:
    return "accessor %s" % ('?' if index is None else index)


def _read_accessor(g: "pygltflib.GLTF2", index: int, resolver: Resolver) -> np.ndarray:
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
    return arr


def _apply_sparse(g: "pygltflib.GLTF2", acc: "pygltflib.Accessor", sparse: "pygltflib.Sparse",
                  base: np.ndarray, dtype: np.dtype, ncomp: int,
                  resolver: Resolver) -> np.ndarray:
    """Scatter a sparse accessor's index->value overrides onto the base array."""
    n = int(sparse.count)
    si, sv = sparse.indices, sparse.values
    idx_dtype = np.dtype(_component_dtype(si.componentType))
    ibv = g.bufferViews[si.bufferView]
    idata = _buffer_bytes(g, ibv.buffer, resolver)
    ioff = (ibv.byteOffset or 0) + (getattr(si, 'byteOffset', 0) or 0)
    indices = np.frombuffer(idata, dtype=idx_dtype, count=n, offset=ioff)
    vbv = g.bufferViews[sv.bufferView]
    vdata = _buffer_bytes(g, vbv.buffer, resolver)
    voff = (vbv.byteOffset or 0) + (getattr(sv, 'byteOffset', 0) or 0)
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
        np.maximum(out, -1.0, out)
    return out


def _read_floats(g: "pygltflib.GLTF2", index: int, resolver: Resolver) -> np.ndarray:
    arr = _read_accessor(g, index, resolver).astype(np.float32)
    return np.ascontiguousarray(arr)


def _read_normalized(g: "pygltflib.GLTF2", index: int, resolver: Resolver) -> np.ndarray:
    """Read an accessor as float32, honoring ``accessor.normalized``.

    Float accessors pass through; integer accessors are divided by their type
    maximum only when flagged ``normalized`` (signed clamped to -1), matching the
    glTF spec rather than assuming every integer attribute is normalized.
    """
    acc = g.accessors[index]
    arr = _read_accessor(g, index, resolver)
    if acc.componentType == _COMPONENT_FLOAT:
        return np.ascontiguousarray(arr.astype(np.float32))
    if getattr(acc, 'normalized', False):
        return np.ascontiguousarray(_normalize_array(arr))
    return np.ascontiguousarray(arr.astype(np.float32))


def _coerce_normalized(acc: "pygltflib.Accessor", arr: np.ndarray) -> np.ndarray:
    """Apply :func:`_read_normalized`'s policy to an already-decoded array.

    The Draco path yields attribute values without the accessor's bufferView, but
    the accessor is still authoritative for componentType/normalized. Float
    accessors pass through as float32; a ``normalized`` integer accessor divides by
    its declared componentType's maximum (signed clamped to -1) -- the divisor comes
    from the accessor, not the decoded array's dtype, so a Draco stream that hands
    back floats is normalized the same as one that hands back integers.
    """
    if acc.componentType == _COMPONENT_FLOAT:
        return np.ascontiguousarray(arr.astype(np.float32))
    if getattr(acc, 'normalized', False):
        return np.ascontiguousarray(
            _normalize_array(arr, _component_dtype(acc.componentType)))
    return np.ascontiguousarray(arr.astype(np.float32))


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
