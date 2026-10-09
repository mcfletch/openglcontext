"""Meshopt-compressed buffer views: ``KHR_meshopt_compression`` and ``EXT_meshopt_compression``.

A buffer view that carries either extension holds its bytes compressed in
another buffer. :func:`decode_view` returns the view's uncompressed bytes,
``byteStride * count`` of them, which the accessors over that view then read as
they read any other view. The two extensions share one bitstream; ``KHR`` adds
version 1 of the attribute codec and the ``COLOR`` filter, and both versions are
read under either name.

The three codecs and four filters are the ones the specification's appendices
define:

    decode_attributes   mode ATTRIBUTES: byte deltas, versions 0 and 1
    decode_triangles    mode TRIANGLES: triangle lists, FIFO-coded
    decode_indices      mode INDICES: any index sequence, two delta baselines
    apply_filter        OCTAHEDRAL, QUATERNION, EXPONENTIAL, COLOR

Specification: the ``KHR_meshopt_compression`` and ``EXT_meshopt_compression``
READMEs in the Khronos glTF repository (Appendix A, bitstream; Appendix B,
filters). Points the prose leaves open (the length of a literal byte run, the
direction of the XOR rotation) follow meshoptimizer's reference decoder, which
is MIT-licensed (Copyright (c) 2016-2026 Arseny Kapoulkine); no code is copied
from it.

The attribute decoder walks the stream once in Python to find where each
group of sixteen deltas starts, then unpacks every group of one width, fills
its sentinels and accumulates the deltas as whole NumPy arrays. Triangle
decoding is a loop per triangle, since each triangle reads FIFOs the previous
one wrote.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np

__all__ = ['EXTENSIONS', 'MeshoptError', 'view_extension', 'is_fallback_buffer',
           'decode_view', 'decode_attributes', 'decode_triangles',
           'decode_indices', 'apply_filter']

#: The extension names a buffer view or buffer may carry, ``KHR`` first.
EXTENSIONS = ('KHR_meshopt_compression', 'EXT_meshopt_compression')


class MeshoptError(ValueError):
    """A meshopt stream that does not decode to the layout its view declares."""


def view_extension(view: Any) -> Optional[Mapping[str, Any]]:
    """The meshopt extension object a buffer view carries, or None."""
    extensions = getattr(view, 'extensions', None) or {}
    for name in EXTENSIONS:
        found = extensions.get(name)
        if isinstance(found, Mapping):
            return found
    return None


def is_fallback_buffer(buffer: Any) -> bool:
    """Whether a buffer is marked as the uncompressed stand-in for meshopt views.

    Such a buffer is never read: every view over it decodes its bytes from the
    compressed buffer its extension names.
    """
    extensions = getattr(buffer, 'extensions', None) or {}
    return any(isinstance(extensions.get(name), Mapping)
               and extensions[name].get('fallback') is True for name in EXTENSIONS)


def _whole(extension: Mapping[str, Any], key: str, default: Optional[int] = None) -> int:
    value = extension.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MeshoptError("meshopt %s is %r, not a non-negative integer" % (key, value))
    return value


def decode_view(extension: Mapping[str, Any], compressed: bytes,
                byte_length: Optional[int] = None) -> bytes:
    """The uncompressed bytes of a meshopt buffer view.

    ``extension`` is the view's extension object (``mode``, ``filter``,
    ``count``, ``byteStride``); ``compressed`` is exactly its
    ``byteOffset``/``byteLength`` range of the buffer it names. ``byte_length``
    is the parent view's own ``byteLength``, which must equal
    ``count * byteStride``.
    """
    count = _whole(extension, 'count')
    stride = _whole(extension, 'byteStride')
    mode = extension.get('mode')
    filter_name = extension.get('filter', 'NONE') or 'NONE'
    if byte_length is not None and byte_length != count * stride:
        raise MeshoptError("meshopt view of %d elements of %d bytes cannot fill a "
                           "view of %d bytes" % (count, stride, byte_length))
    if mode == 'ATTRIBUTES':
        decoded = decode_attributes(compressed, count, stride)
        return apply_filter(filter_name, decoded).tobytes()
    if filter_name != 'NONE':
        raise MeshoptError("meshopt filter %r applies to ATTRIBUTES, not %r"
                           % (filter_name, mode))
    if mode == 'TRIANGLES':
        return decode_triangles(compressed, count, stride).tobytes()
    if mode == 'INDICES':
        return decode_indices(compressed, count, stride).tobytes()
    raise MeshoptError("unknown meshopt mode %r" % (mode,))


# --------------------------------------------------------------------------- #
# Mode 0: attributes
# --------------------------------------------------------------------------- #
_BLOCK_BYTES = 8192
_BLOCK_MAX = 256
_GROUP = 16
#: Bytes that must remain after a group starts; the tail padding guarantees it.
_GROUP_DECODE_LIMIT = 24
_TAIL_MINIMUM = {0: 32, 1: 24}
#: Bit widths each two-bit group header selects: version 0, and version 1 under
#: control modes 0 and 1.
_WIDTHS_V0 = (0, 2, 4, 8)
_WIDTHS_V1 = ((0, 1, 2, 4), (1, 2, 4, 8))


def _sentinel_table(bits: int) -> bytes:
    """For each byte value, how many of its packed deltas are sentinels."""
    sentinel = (1 << bits) - 1
    table = bytearray(256)
    for value in range(256):
        table[value] = sum(1 for shift in range(0, 8, bits)
                           if (value >> shift) & sentinel == sentinel)
    return bytes(table)


_SENTINELS = {bits: _sentinel_table(bits) for bits in (1, 2, 4)}


def _block_size(stride: int) -> int:
    return min((_BLOCK_BYTES // stride) & ~(_GROUP - 1), _BLOCK_MAX)


def decode_attributes(data: bytes, count: int, stride: int) -> np.ndarray:
    """Mode ATTRIBUTES: ``count`` elements of ``stride`` bytes, as a
    ``(count, stride)`` uint8 array."""
    if stride < 4 or stride > 256 or stride % 4:
        raise MeshoptError("meshopt ATTRIBUTES byteStride %d is not a multiple of "
                           "4 in [4, 256]" % stride)
    data = bytes(data)
    size = len(data)
    if size < 1 or data[0] & 0xF0 != 0xA0:
        raise MeshoptError("meshopt attribute stream has no 0xa0/0xa1 header")
    version = data[0] & 0x0F
    if version > 1:
        raise MeshoptError("meshopt attribute stream version %d is not 0 or 1" % version)
    tail_size = stride + (stride // 4 if version else 0)
    tail_padded = max(tail_size, _TAIL_MINIMUM[version])
    if size - 1 < tail_padded:
        raise MeshoptError("meshopt attribute stream is shorter than its tail")
    tail = data[size - tail_size:]
    baseline = np.frombuffer(tail, np.uint8, count=stride)
    channels = tail[stride:] if version else bytes(stride // 4)

    # Deltas, laid out as the decoded elements are: one row per element. The
    # last block's final group may run up to fifteen rows past ``count``.
    deltas = np.zeros((count + _GROUP, stride), np.uint8)
    tasks: dict[int, tuple[list[int], list[int], list[int]]] = {
        bits: ([], [], []) for bits in (1, 2, 4, 8)}
    position = 1
    start = 0
    block = _block_size(stride)
    while start < count:
        elements = min(block, count - start)
        groups = (elements + _GROUP - 1) // _GROUP
        if version:
            control = data[position:position + stride // 4]
            if len(control) < stride // 4:
                raise MeshoptError("meshopt attribute block ends in its control bytes")
            position += stride // 4
        for byte in range(stride):
            mode = (control[byte >> 2] >> ((byte & 3) << 1)) & 3 if version else 0
            if mode == 3:
                if size - position < elements:
                    raise MeshoptError("meshopt literal run passes the stream's end")
                deltas[start:start + elements, byte] = np.frombuffer(
                    data, np.uint8, count=elements, offset=position)
                position += elements
                continue
            if mode == 2:
                continue
            widths = _WIDTHS_V1[mode] if version else _WIDTHS_V0
            header_size = (groups + 3) // 4
            header = data[position:position + header_size]
            if len(header) < header_size:
                raise MeshoptError("meshopt attribute block ends in its group headers")
            position += header_size
            for group in range(groups):
                if size - position < _GROUP_DECODE_LIMIT:
                    raise MeshoptError("meshopt attribute group passes the stream's end")
                bits = widths[(header[group >> 2] >> ((group & 3) << 1)) & 3]
                if not bits:
                    continue
                rows, columns, starts = tasks[bits]
                rows.append(start + group * _GROUP)
                columns.append(byte)
                starts.append(position)
                if bits == 8:
                    position += _GROUP
                else:
                    packed = 2 * bits
                    position += packed + sum(
                        data[position:position + packed].translate(_SENTINELS[bits]))
        start += elements
    if position != size - tail_padded:
        raise MeshoptError("meshopt attribute stream holds %d bytes its elements do "
                           "not account for" % (size - tail_padded - position))
    stream = np.frombuffer(data, np.uint8)
    for bits, (rows, columns, starts) in tasks.items():
        if rows:
            _unpack_groups(stream, deltas, bits, np.array(rows), np.array(columns),
                           np.array(starts))
    return _accumulate(deltas[:count], baseline, channels, stride)


def _unpack_groups(stream: np.ndarray, deltas: np.ndarray, bits: int,
                   rows: np.ndarray, columns: np.ndarray, starts: np.ndarray) -> None:
    """Every group of one bit width, unpacked into ``deltas`` at its rows."""
    lanes = np.arange(_GROUP)
    if bits == 8:
        values = stream[starts[:, None] + lanes]
    else:
        packed = 2 * bits
        raw = stream[starts[:, None] + np.arange(packed)].astype(np.uint16)
        per_byte = 8 // bits
        if bits == 1:
            # Least significant bit first, unlike the wider widths.
            shifts = np.arange(per_byte)
        else:
            shifts = (per_byte - 1 - np.arange(per_byte)) * bits
        values = ((raw[:, :, None] >> shifts) & ((1 << bits) - 1)).reshape(-1, _GROUP)
        sentinel = values == (1 << bits) - 1
        extra = np.cumsum(sentinel, axis=1) - 1
        source = starts[:, None] + packed + extra
        values = np.where(sentinel, stream[np.where(sentinel, source, 0)], values)
    deltas[rows[:, None] + lanes, columns[:, None]] = values


def _unzigzag(values: np.ndarray) -> np.ndarray:
    decoded: np.ndarray = (values >> 1) ^ (values.dtype.type(0) - (values & 1))
    return decoded


def _accumulate(deltas: np.ndarray, baseline: np.ndarray, channels: bytes,
                stride: int) -> np.ndarray:
    """The elements, from their deltas and the baseline, channel by channel."""
    count = len(deltas)
    out = np.empty((count, stride), np.uint8)
    for channel in range(stride // 4):
        mode = channels[channel]
        columns = slice(channel * 4, channel * 4 + 4)
        delta = np.ascontiguousarray(deltas[:, columns])
        base = np.ascontiguousarray(baseline[columns])
        if mode & 3 == 0 and not mode >> 4:
            values = np.cumsum(_unzigzag(delta), axis=0, dtype=np.uint8) + base
        elif mode & 3 == 1 and not mode >> 4:
            wide = delta.view('<u2')
            values = (np.cumsum(_unzigzag(wide), axis=0, dtype=np.uint16)
                      + base.view('<u2')).view(np.uint8)
        elif mode & 3 == 2:
            word = delta.view('<u4')
            turn = np.uint32((32 - (mode >> 4)) & 31)
            word = (word << turn) | (word >> np.uint32((32 - int(turn)) & 31))
            values = (np.bitwise_xor.accumulate(word, axis=0)
                      ^ base.view('<u4')).view(np.uint8)
        else:
            raise MeshoptError("meshopt channel mode 0x%02x is not defined" % mode)
        out[:, columns] = values.reshape(count, 4)
    return out


# --------------------------------------------------------------------------- #
# Mode 1: triangles
# --------------------------------------------------------------------------- #
_MASK32 = 0xFFFFFFFF


def decode_triangles(data: bytes, count: int, stride: int) -> np.ndarray:
    """Mode TRIANGLES: ``count`` indices (a multiple of three) as uint16 or
    uint32 by ``stride``."""
    if stride not in (2, 4):
        raise MeshoptError("meshopt index byteStride %d is not 2 or 4" % stride)
    if count % 3:
        raise MeshoptError("meshopt TRIANGLES count %d is not a multiple of 3" % count)
    data = bytes(data)
    triangles = count // 3
    if len(data) < 1 + triangles + 16:
        raise MeshoptError("meshopt triangle stream is shorter than its codes")
    if data[0] & 0xF0 != 0xE0 or data[0] & 0x0F > 1:
        raise MeshoptError("meshopt triangle stream has no 0xe0/0xe1 header")
    fec_limit = 13 if data[0] & 0x0F else 15
    safe_end = len(data) - 16
    codeaux = data[safe_end:]
    out = np.empty(count, np.uint32)
    edges = [(_MASK32, _MASK32)] * 16
    vertices = [_MASK32] * 16
    edge_at = vertex_at = 0
    following = last = 0
    cursor = 1 + triangles
    write = 0

    def varint() -> int:
        nonlocal cursor
        value = shift = 0
        for _ in range(5):
            byte = data[cursor]
            cursor += 1
            value |= (byte & 0x7F) << shift
            shift += 7
            if byte < 0x80:
                break
        return value & _MASK32

    def delta_index() -> int:
        nonlocal last
        value = varint()
        last = (last + ((value >> 1) ^ -(value & 1))) & _MASK32
        return last

    for code in data[1:1 + triangles]:
        if code < 0xF0:
            a, b = edges[(edge_at - 1 - (code >> 4)) & 15]
            fec = code & 15
            if fec < fec_limit:
                if fec:
                    c = vertices[(vertex_at - 1 - fec) & 15]
                else:
                    c = following
                    following = (following + 1) & _MASK32
                    vertices[vertex_at] = c
                    vertex_at = (vertex_at + 1) & 15
            else:
                if cursor > safe_end:
                    raise MeshoptError("meshopt triangle data passes its codeaux table")
                if fec != 15:
                    c = last = (last + fec * 2 - 27) & _MASK32
                else:
                    c = delta_index()
                vertices[vertex_at] = c
                vertex_at = (vertex_at + 1) & 15
            edges[edge_at] = (c, b)
            edges[(edge_at + 1) & 15] = (a, c)
            edge_at = (edge_at + 2) & 15
        else:
            if code < 0xFE:
                aux = codeaux[code & 15]
                explicit_a = False
            else:
                if cursor > safe_end:
                    raise MeshoptError("meshopt triangle data passes its codeaux table")
                aux = data[cursor]
                cursor += 1
                if aux == 0:
                    following = 0
                explicit_a = code == 0xFF
            feb, fec = aux >> 4, aux & 15
            if explicit_a:
                a = 0
            else:
                a = following
                following = (following + 1) & _MASK32
            if feb == 0:
                b = following
                following = (following + 1) & _MASK32
            else:
                b = vertices[(vertex_at - feb) & 15]
            if fec == 0:
                c = following
                following = (following + 1) & _MASK32
            else:
                c = vertices[(vertex_at - fec) & 15]
            if explicit_a:
                a = delta_index()
            if feb == 15:
                b = delta_index()
            if fec == 15:
                c = delta_index()
            vertices[vertex_at] = a
            vertex_at = (vertex_at + 1) & 15
            if feb in (0, 15):
                vertices[vertex_at] = b
                vertex_at = (vertex_at + 1) & 15
            if fec in (0, 15):
                vertices[vertex_at] = c
                vertex_at = (vertex_at + 1) & 15
            edges[edge_at] = (b, a)
            edges[(edge_at + 1) & 15] = (c, b)
            edges[(edge_at + 2) & 15] = (a, c)
            edge_at = (edge_at + 3) & 15
        out[write:write + 3] = (a, b, c)
        write += 3
    if cursor != safe_end:
        raise MeshoptError("meshopt triangle stream holds %d bytes its triangles do "
                           "not account for" % (safe_end - cursor))
    return out if stride == 4 else out.astype(np.uint16)


# --------------------------------------------------------------------------- #
# Mode 2: indices
# --------------------------------------------------------------------------- #
def decode_indices(data: bytes, count: int, stride: int) -> np.ndarray:
    """Mode INDICES: ``count`` indices as uint16 or uint32 by ``stride``."""
    if stride not in (2, 4):
        raise MeshoptError("meshopt index byteStride %d is not 2 or 4" % stride)
    stream = np.frombuffer(bytes(data), np.uint8)
    if len(stream) < 1 + count + 4:
        raise MeshoptError("meshopt index stream is shorter than its indices")
    if stream[0] & 0xF0 != 0xD0 or stream[0] & 0x0F > 1:
        raise MeshoptError("meshopt index stream has no 0xd0/0xd1 header")
    body = stream[1:len(stream) - 4]
    ends = np.flatnonzero(body < 0x80)
    if len(ends) < count or (count and ends[count - 1] != len(body) - 1) \
            or (not count and len(body)):
        raise MeshoptError("meshopt index stream does not hold exactly %d indices"
                           % count)
    if not count:
        return np.zeros(0, np.uint32 if stride == 4 else np.uint16)
    starts = np.concatenate([[0], ends[:-1] + 1])
    lengths = ends - starts + 1
    if lengths.max() > 5:
        raise MeshoptError("meshopt index varint runs past five bytes")
    owner = np.repeat(np.arange(count), lengths)
    place = np.arange(len(body)) - starts[owner]
    value = np.zeros(count, np.uint64)
    np.add.at(value, owner, (body.astype(np.uint64) & 0x7F) << (7 * place).astype(np.uint64))
    value = (value & _MASK32).astype(np.uint32)
    which = value & 1
    value >>= 1
    delta = (value >> 1) ^ (np.uint32(0) - (value & 1))
    out = np.empty(count, np.uint32)
    for baseline in (0, 1):
        chosen = which == baseline
        out[chosen] = np.cumsum(np.where(chosen, delta, 0), dtype=np.uint32)[chosen]
    return out if stride == 4 else out.astype(np.uint16)


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def _round_away(values: np.ndarray) -> np.ndarray:
    """Round half away from zero, as the filters specify."""
    rounded: np.ndarray = np.trunc(values + np.copysign(0.5, values))
    return rounded


def apply_filter(name: str, elements: np.ndarray) -> np.ndarray:
    """``elements`` (a ``(count, stride)`` uint8 array) after the named filter."""
    if name == 'NONE':
        return elements
    stride = elements.shape[1]
    allowed = {'OCTAHEDRAL': (4, 8), 'QUATERNION': (8,), 'COLOR': (4, 8)}
    if name == 'EXPONENTIAL':
        if stride % 4:
            raise MeshoptError("meshopt EXPONENTIAL needs a byteStride divisible by 4")
        return _exponential(elements)
    if name not in allowed:
        raise MeshoptError("unknown meshopt filter %r" % (name,))
    if stride not in allowed[name]:
        raise MeshoptError("meshopt %s needs a byteStride of %s, not %d"
                           % (name, ' or '.join(map(str, allowed[name])), stride))
    if name == 'OCTAHEDRAL':
        return _octahedral(elements)
    if name == 'QUATERNION':
        return _quaternion(elements)
    return _color(elements)


def _octahedral(elements: np.ndarray) -> np.ndarray:
    signed = np.dtype('<i1' if elements.shape[1] == 4 else '<i2')
    components = elements.view(signed).reshape(-1, 4)
    limit = float(np.iinfo(signed).max)
    one = components[:, 2].astype(np.float64)
    one[one == 0] = 1.0                     # not a valid K-bit 1.0; unspecified
    x = components[:, 0] / one
    y = components[:, 1] / one
    z = 1.0 - np.abs(x) - np.abs(y)
    fold = np.minimum(z, 0.0)
    x = x - np.copysign(fold, x)
    y = y - np.copysign(fold, y)
    length = np.sqrt(x * x + y * y + z * z)
    out = components.copy()
    for column, value in enumerate((x, y, z)):
        out[:, column] = _round_away(value / length * limit)
    return out.view(np.uint8).reshape(elements.shape)


def _quaternion(elements: np.ndarray) -> np.ndarray:
    components = elements.view('<i2').reshape(-1, 4).astype(np.int32)
    scale = 1.0 / np.sqrt(2.0)
    one = (components[:, 3] | 3).astype(np.float64)
    x = components[:, 0] / one * scale
    y = components[:, 1] / one * scale
    z = components[:, 2] / one * scale
    w = np.sqrt(np.maximum(0.0, 1.0 - x * x - y * y - z * z))
    largest = components[:, 3] & 3
    rows = np.arange(len(components))
    out = np.empty((len(components), 4), '<i2')
    for offset, value in ((1, x), (2, y), (3, z), (0, w)):
        out[rows, (largest + offset) % 4] = _round_away(value * 32767.0)
    return out.view(np.uint8).reshape(elements.shape)


def _exponential(elements: np.ndarray) -> np.ndarray:
    words = elements.view('<i4').reshape(-1)
    exponent = words >> 24
    mantissa = (words << 8) >> 8
    with np.errstate(over='ignore'):
        values = np.ldexp(mantissa.astype(np.float64), exponent).astype('<f4')
    decoded: np.ndarray = values.view(np.uint8).reshape(elements.shape)
    return decoded


def _color(elements: np.ndarray) -> np.ndarray:
    wide = elements.shape[1] == 8
    unsigned = np.dtype('<u2' if wide else 'u1')
    signed = np.dtype('<i2' if wide else 'i1')
    components = elements.view(unsigned).reshape(-1, 4)
    limit = float(np.iinfo(unsigned).max)
    alpha_bits = components[:, 3].astype(np.int64)
    _mantissa, exponent = np.frexp(alpha_bits.astype(np.float64))
    scale_max = (np.int64(1) << exponent.astype(np.int64)) - 1   # (1 << (msb + 1)) - 1
    luma = components[:, 0].astype(np.int64)
    co = components[:, 1].view(signed).astype(np.int64)
    cg = components[:, 2].view(signed).astype(np.int64)
    red = luma + co - cg
    green = luma + cg
    blue = luma - co - cg
    alpha = alpha_bits & (scale_max >> 1)
    alpha = (alpha << 1) | (alpha & 1)
    factor = limit / np.where(scale_max == 0, 1, scale_max).astype(np.float64)
    out = np.empty((len(components), 4), unsigned)
    for column, value in enumerate((red, green, blue, alpha)):
        out[:, column] = np.clip(_round_away(value * factor), 0, limit)
    return out.view(np.uint8).reshape(elements.shape)
