"""Cube maps and volumes from the files that carry them -- no GL

PIL reads one picture from a file; a cube map is six and a volume is a stack,
and the formats that carry them are read here into numpy arrays the texture
nodes upload (:mod:`OpenGLContext.scenegraph.cubemaptexture`,
:mod:`OpenGLContext.scenegraph.texture3d`):

- DDS (Microsoft DirectDraw Surface): cube maps, volumes and single images;
  uncompressed formats given by their channel masks (8 to 32 bits a pixel,
  luminance, alpha, RGB and RGBA), BC1, BC2 and BC3 (DXT1, DXT3, DXT5), and
  the DX10 header's 8-bit RGBA, BGRA and single-channel formats and BC1 to
  BC3. Only the first mip level is read.
- KTX 1.1 (Khronos): cube maps, volumes and single images of unsigned bytes
  (luminance, alpha, red, RG, RGB, RGBA, BGR, BGRA) or of the S3TC formats.
  KTX 2 is not read.
- NRRD (teem's "nearly raw raster data"): volumes of one to four
  components, raw, gzip, bzip2 or text encoded, attached or in a detached
  data file. Samples wider than a byte are scaled from their range in the
  volume to 0..255. :func:`nrrd_bytes` writes a uint8 volume as one.
- A single picture holding six faces, read by :func:`cube_from_layout`: a
  horizontal cross (4x3 faces), a vertical cross (3x4), a strip of six in a
  row or a column, or 3x2.

A cube map is answered as six ``(n, n, c)`` uint8 arrays in GL's face order,
+X, -X, +Y, -Y, +Z, -Z, each with its top row first as GL lays a face out. A
volume is a ``(depth, height, width, c)`` uint8 array whose first slice is r=0
and whose first row in a slice is t=0. ``c`` is 1 to 4 channels: luminance,
luminance and alpha, RGB or RGBA.

The bytes come from a document and are not trusted: every size is checked
against what the data holds and against :data:`MAX_TEXELS` before anything is
allocated, and a file that does not hold what it says raises
:class:`TextureImageError`.
"""
from __future__ import annotations

import bz2
import gzip
import struct
import zlib
from collections.abc import Callable, Sequence
from typing import Optional

import numpy as np

__all__ = [
    'MAX_TEXELS', 'TextureImageError', 'CubeFaces', 'Volume',
    'read_cube', 'read_volume', 'cube_from_layout', 'is_dds', 'is_ktx', 'is_nrrd',
    'nrrd_bytes', 'read_dds', 'read_ktx', 'read_nrrd',
]

#: The most texels a cube map or a volume read here may hold (all faces or
#: slices together): a gigabyte at four channels.
MAX_TEXELS = 1 << 28

#: Six faces in GL's order: +X, -X, +Y, -Y, +Z, -Z.
CubeFaces = list
#: A ``(depth, height, width, channels)`` uint8 array.
Volume = np.ndarray


class TextureImageError(ValueError):
    """Bytes that are not the cube map or volume they claim to be."""


def _check_size(*dimensions: int) -> None:
    total = 1
    for value in dimensions:
        if value <= 0:
            raise TextureImageError('an image dimension of %d' % (value,))
        total *= value
    if total > MAX_TEXELS:
        raise TextureImageError('%s texels is more than the %d allowed'
                                % ('x'.join(str(value) for value in dimensions), MAX_TEXELS))


# -- DDS -----------------------------------------------------------------------

_DDS_MAGIC = b'DDS '
_DDSD_DEPTH = 0x800000
_DDPF_ALPHAPIXELS = 0x1
_DDPF_ALPHA = 0x2
_DDPF_FOURCC = 0x4
_DDPF_RGB = 0x40
_DDPF_LUMINANCE = 0x20000
_DDSCAPS2_CUBEMAP = 0x200
_DDSCAPS2_VOLUME = 0x200000
#: The face flags of a cube map in DDS, in GL's face order.
_DDS_FACES = (0x400, 0x800, 0x1000, 0x2000, 0x4000, 0x8000)
_DX10_TEXTURECUBE = 0x4
_DIMENSION_3D = 4

#: Block-compressed formats: (bytes a 4x4 block, Pillow's BCn decoder number).
_BLOCKS = {
    b'DXT1': (8, 1), b'DXT2': (16, 2), b'DXT3': (16, 2), b'DXT4': (16, 3), b'DXT5': (16, 3),
}
#: The DX10 header's formats read here: a block format, or (channels, order).
_DXGI_BLOCKS = {70: (8, 1), 71: (8, 1), 72: (8, 1), 73: (16, 2), 74: (16, 2),
                75: (16, 2), 76: (16, 3), 77: (16, 3), 78: (16, 3)}
_DXGI_PLAIN = {27: (4, 'RGBA'), 28: (4, 'RGBA'), 29: (4, 'RGBA'),
               87: (4, 'BGRA'), 88: (4, 'BGRX'), 90: (4, 'BGRA'), 91: (4, 'BGRA'),
               92: (4, 'BGRX'), 93: (4, 'BGRX'), 60: (1, 'L'), 61: (1, 'L'),
               62: (1, 'L'), 63: (1, 'L'), 65: (1, 'A')}


def is_dds(data: bytes) -> bool:
    """Whether ``data`` starts as a DDS file does"""
    return data[:4] == _DDS_MAGIC


class _Format:
    """How one DDS or KTX image's bytes become pixels"""

    def __init__(self, channels: int, decode: Callable[[bytes, int, int], np.ndarray],
                 size: Callable[[int, int], int]) -> None:
        self.channels = channels
        self.decode = decode
        self.size = size


def _block_format(block_bytes: int, decoder: int) -> _Format:
    def size(width: int, height: int) -> int:
        return ((width + 3) // 4) * ((height + 3) // 4) * block_bytes

    def decode(data: bytes, width: int, height: int) -> np.ndarray:
        from PIL import Image  # noqa: PLC0415 Pillow's block decoder, only for compressed images
        padded = (((width + 3) // 4) * 4, ((height + 3) // 4) * 4)
        image = Image.frombytes('RGBA', padded, data, 'bcn', decoder)
        return np.asarray(image)[:height, :width]
    return _Format(4, decode, size)


def _order_format(channels: int, order: str) -> _Format:
    width_bytes = len(order)

    def size(width: int, height: int) -> int:
        return width * height * width_bytes

    def decode(data: bytes, width: int, height: int) -> np.ndarray:
        pixels = np.frombuffer(data, np.uint8).reshape(height, width, width_bytes)
        if order in ('L', 'A', 'RGBA', 'RGB', 'LA'):
            return pixels
        if order == 'BGRA':
            return pixels[..., [2, 1, 0, 3]]
        if order == 'BGR':
            return pixels[..., [2, 1, 0]]
        return pixels[..., [2, 1, 0]]          # BGRX
    return _Format(channels, decode, size)


def _mask_format(bits: int, masks: Sequence[int], flags: int) -> _Format:
    """An uncompressed DDS format given by its channel bit masks"""
    if bits not in (8, 16, 24, 32):
        raise TextureImageError('a DDS image of %d bits a pixel' % (bits,))
    red, green, blue, alpha = masks
    if flags & _DDPF_LUMINANCE:
        wanted = [red] + ([alpha] if flags & _DDPF_ALPHAPIXELS else [])
    elif flags & _DDPF_ALPHA and not flags & _DDPF_RGB:
        wanted = [alpha]
    else:
        wanted = [red, green, blue] + ([alpha] if flags & _DDPF_ALPHAPIXELS and alpha else [])
    stride = bits // 8

    def size(width: int, height: int) -> int:
        return width * height * stride

    def decode(data: bytes, width: int, height: int) -> np.ndarray:
        raw = np.frombuffer(data, np.uint8).reshape(height * width, stride).astype(np.uint32)
        values = np.zeros(height * width, np.uint32)
        for index in range(stride):
            values |= raw[:, index] << np.uint32(8 * index)
        out: list[np.ndarray] = []
        for mask in wanted:
            if not mask:
                out.append(np.zeros(len(values), np.uint8))
                continue
            shift = (mask & -mask).bit_length() - 1
            top = mask >> shift
            out.append(((values & np.uint32(mask)) >> np.uint32(shift)).astype(np.float64)
                       * (255.0 / top))
        return np.round(np.stack(out, -1)).astype(np.uint8).reshape(height, width, len(wanted))
    return _Format(len(wanted), decode, size)


def _dds_header(data: bytes) -> tuple[dict, _Format, int]:
    """The DDS header's fields, the pixel format and where the images start"""
    if not is_dds(data) or len(data) < 128:
        raise TextureImageError('not a DDS file')
    (size, flags, height, width, _pitch, depth, _mips) = struct.unpack_from('<7I', data, 4)
    if size != 124:
        raise TextureImageError('a DDS header of %d bytes' % (size,))
    (pf_size, pf_flags, fourcc, bits, red, green, blue, alpha) = struct.unpack_from(
        '<2I4s5I', data, 76)
    (caps, caps2) = struct.unpack_from('<2I', data, 108)
    header = dict(width=width, height=height,
                  depth=depth if flags & _DDSD_DEPTH and caps2 & _DDSCAPS2_VOLUME else 1,
                  faces=[index for index, flag in enumerate(_DDS_FACES) if caps2 & flag]
                  if caps2 & _DDSCAPS2_CUBEMAP else [],
                  volume=bool(caps2 & _DDSCAPS2_VOLUME))
    offset = 128
    if pf_flags & _DDPF_FOURCC:
        if fourcc == b'DX10':
            if len(data) < 148:
                raise TextureImageError('a DDS file cut short in its DX10 header')
            dxgi, dimension, misc, array_size = struct.unpack_from('<4I', data, 128)
            offset = 148
            if misc & _DX10_TEXTURECUBE:
                header['faces'] = list(range(6))
            header['volume'] = dimension == _DIMENSION_3D
            if not header['volume']:
                header['depth'] = 1
            if dxgi in _DXGI_BLOCKS:
                return header, _block_format(*_DXGI_BLOCKS[dxgi]), offset
            if dxgi in _DXGI_PLAIN:
                channels, order = _DXGI_PLAIN[dxgi]
                return header, _order_format(channels, order), offset
            raise TextureImageError('DDS DXGI format %d is not read' % (dxgi,))
        if fourcc in _BLOCKS:
            return header, _block_format(*_BLOCKS[fourcc]), offset
        raise TextureImageError('DDS format %r is not read' % (fourcc,))
    return header, _mask_format(bits, (red, green, blue, alpha), pf_flags), offset


def _mip_bytes(form: _Format, width: int, height: int, mips: int) -> int:
    """The bytes of every mip level of one image after the first"""
    total = 0
    for level in range(1, mips):
        total += form.size(max(1, width >> level), max(1, height >> level))
    return total


def read_dds(data: bytes) -> tuple[str, list[np.ndarray]]:
    """The kind of image a DDS file holds and its pixels

    ``('cube', faces)`` for a cube map, ``('volume', [volume])`` for a volume
    texture and ``('image', [pixels])`` for a single image, each as the module
    describes. A cube map missing faces raises :class:`TextureImageError`.
    """
    header, form, offset = _dds_header(data)
    width, height, depth = header['width'], header['height'], header['depth']
    mips = max(1, struct.unpack_from('<I', data, 28)[0])
    if header['faces']:
        if len(header['faces']) != 6:
            raise TextureImageError('a DDS cube map with %d faces' % (len(header['faces']),))
        _check_size(width, height, 6)
        step = form.size(width, height)
        skip = _mip_bytes(form, width, height, mips)
        faces = []
        for _face in range(6):
            faces.append(_take(form, data, offset, width, height))
            offset += step + skip
        return 'cube', faces
    if header['volume'] and depth > 1:
        _check_size(width, height, depth)
        step = form.size(width, height)
        slices = [_take(form, data, offset + index * step, width, height)
                  for index in range(depth)]
        # A DDS image has its top row first; a volume here has t=0 first.
        return 'volume', [np.ascontiguousarray(np.stack(slices)[:, ::-1])]
    _check_size(width, height)
    return 'image', [_take(form, data, offset, width, height)]


def _take(form: _Format, data: bytes, offset: int, width: int, height: int) -> np.ndarray:
    size = form.size(width, height)
    if offset + size > len(data):
        raise TextureImageError('an image file cut short: %d bytes wanted at %d of %d'
                                % (size, offset, len(data)))
    return form.decode(data[offset:offset + size], width, height)


# -- KTX 1.1 -------------------------------------------------------------------

_KTX_MAGIC = b'\xabKTX 11\xbb\r\n\x1a\n'
_GL_UNSIGNED_BYTE = 0x1401
#: Uncompressed formats: GL format -> (channels, order).
_KTX_PLAIN = {0x1909: (1, 'L'), 0x1906: (1, 'A'), 0x1903: (1, 'L'), 0x190A: (2, 'LA'),
              0x8227: (2, 'LA'), 0x1907: (3, 'RGB'), 0x1908: (4, 'RGBA'),
              0x80E0: (3, 'BGR'), 0x80E1: (4, 'BGRA')}
#: S3TC formats: GL internal format -> (bytes a block, Pillow's decoder).
_KTX_BLOCKS = {0x83F0: (8, 1), 0x83F1: (8, 1), 0x83F2: (16, 2), 0x83F3: (16, 3),
               0x8C4C: (8, 1), 0x8C4D: (8, 1), 0x8C4E: (16, 2), 0x8C4F: (16, 3)}


def is_ktx(data: bytes) -> bool:
    """Whether ``data`` starts as a KTX 1.1 file does"""
    return data[:12] == _KTX_MAGIC


def read_ktx(data: bytes) -> tuple[str, list[np.ndarray]]:
    """The kind of image a KTX 1.1 file holds and its pixels, as :func:`read_dds` answers"""
    if not is_ktx(data) or len(data) < 64:
        raise TextureImageError('not a KTX 1.1 file')
    endian = struct.unpack_from('<I', data, 12)[0]
    order = '<' if endian == 0x04030201 else '>'
    (gl_type, _type_size, gl_format, internal, _base, width, height, depth,
     _elements, faces, _mips, key_bytes) = struct.unpack_from(order + '12I', data, 16)
    if gl_type == 0:
        if internal not in _KTX_BLOCKS:
            raise TextureImageError('KTX compressed format 0x%x is not read' % (internal,))
        form = _block_format(*_KTX_BLOCKS[internal])
        padding = 1
    else:
        if gl_type != _GL_UNSIGNED_BYTE or gl_format not in _KTX_PLAIN:
            raise TextureImageError('KTX format 0x%x of type 0x%x is not read'
                                    % (gl_format, gl_type))
        form = _order_format(*_KTX_PLAIN[gl_format])
        padding = 4
    height = max(1, height)
    offset = 64 + key_bytes + 4          # past the key/values and the first imageSize
    row = form.size(width, 1) if gl_type else 0

    def image_at(at: int) -> tuple[np.ndarray, int]:
        if gl_type and row % padding:
            # Each row of an uncompressed image is padded to four bytes.
            padded = row + padding - row % padding
            need = padded * height
            if at + need > len(data):
                raise TextureImageError('a KTX file cut short')
            rows = np.frombuffer(data, np.uint8, need, at).reshape(height, padded)[:, :row]
            return form.decode(rows.tobytes(), width, height), need
        size = form.size(width, height)
        return _take(form, data, at, width, height), size

    if faces == 6:
        _check_size(width, height, 6)
        found = []
        for _face in range(6):
            pixels, size = image_at(offset)
            found.append(pixels)
            offset += size + (-size) % 4
        return 'cube', found
    if depth > 1:
        _check_size(width, height, depth)
        slices = []
        for _slice in range(depth):
            pixels, size = image_at(offset)
            slices.append(pixels)
            offset += size
        # KTX images, like GL's, have their first row at t=0.
        return 'volume', [np.ascontiguousarray(np.stack(slices))]
    _check_size(width, height)
    pixels, _size = image_at(offset)
    # A KTX image's first row is t=0: turned so the top row is first.
    return 'image', [np.ascontiguousarray(pixels[::-1])]


# -- NRRD ----------------------------------------------------------------------

_NRRD_TYPES = {
    'uchar': np.uint8, 'unsigned char': np.uint8, 'uint8': np.uint8, 'uint8_t': np.uint8,
    'signed char': np.int8, 'char': np.int8, 'int8': np.int8, 'int8_t': np.int8,
    'short': np.int16, 'short int': np.int16, 'signed short': np.int16,
    'signed short int': np.int16, 'int16': np.int16, 'int16_t': np.int16,
    'ushort': np.uint16, 'unsigned short': np.uint16, 'unsigned short int': np.uint16,
    'uint16': np.uint16, 'uint16_t': np.uint16,
    'int': np.int32, 'signed int': np.int32, 'int32': np.int32, 'int32_t': np.int32,
    'uint': np.uint32, 'unsigned int': np.uint32, 'uint32': np.uint32, 'uint32_t': np.uint32,
    'longlong': np.int64, 'long long': np.int64, 'int64': np.int64, 'int64_t': np.int64,
    'ulonglong': np.uint64, 'unsigned long long': np.uint64, 'uint64': np.uint64,
    'uint64_t': np.uint64, 'float': np.float32, 'double': np.float64,
}


#: The NRRD axis kinds that are positions rather than a pixel's components.
_SPATIAL_KINDS = frozenset(('domain', 'space', 'time', 'none', '???'))


def is_nrrd(data: bytes) -> bool:
    """Whether ``data`` starts as an NRRD file or detached header does"""
    return data[:4] == b'NRRD'


def read_nrrd(data: bytes,
              fetch: Optional[Callable[[str], bytes]] = None) -> tuple[str, list[np.ndarray]]:
    """``('volume', [volume])`` from an NRRD file

    ``fetch`` reads a detached data file the header names, by its name as
    written there (relative to the header); without one a detached file
    raises :class:`TextureImageError`. A volume of two dimensions is one
    slice deep; with four, the first axis is the channels (one to four).
    """
    if not is_nrrd(data):
        raise TextureImageError('not an NRRD file')
    end = data.find(b'\n\n')
    if end < 0:
        end = data.find(b'\r\n\r\n')
        body = data[end + 4:] if end >= 0 else b''
    else:
        body = data[end + 2:]
    if end < 0:
        end = len(data)
    fields: dict[str, str] = {}
    for line in data[:end].decode('latin-1').splitlines()[1:]:
        if not line or line.startswith('#') or ':=' in line:
            continue
        key, _, value = line.partition(':')
        fields[key.strip().lower()] = value.strip()
    kind = _NRRD_TYPES.get(fields.get('type', '').lower())
    if kind is None:
        raise TextureImageError('NRRD type %r is not read' % (fields.get('type'),))
    try:
        sizes = [int(value) for value in fields.get('sizes', '').split()]
    except ValueError as err:
        raise TextureImageError('NRRD sizes %r' % (fields.get('sizes'),)) from err
    if not 2 <= len(sizes) <= 4:
        raise TextureImageError('an NRRD of %d dimensions' % (len(sizes),))
    # The first axis is the components with four axes, or with three where
    # the header's kinds say it is not a spatial one.
    kinds = fields.get('kinds', '').lower().split()
    channels = 1
    if len(sizes) == 4 or (len(sizes) == 3 and kinds and kinds[0] not in _SPATIAL_KINDS):
        channels = sizes[0]
        sizes = sizes[1:]
    if not 1 <= channels <= 4:
        raise TextureImageError('an NRRD volume of %d components' % (channels,))
    width, height = sizes[0], sizes[1]
    depth = sizes[2] if len(sizes) > 2 else 1
    _check_size(width, height, depth, channels)
    detached = fields.get('data file') or fields.get('datafile')
    if detached:
        if fetch is None:
            raise TextureImageError('the NRRD data is in %r, which was not read' % (detached,))
        body = fetch(detached)
    encoding = fields.get('encoding', 'raw').lower()
    count = width * height * depth * channels
    dtype = np.dtype(kind)
    if dtype.itemsize > 1:
        dtype = dtype.newbyteorder('>' if fields.get('endian', 'little') == 'big' else '<')
    skip = _whole(fields.get('byte skip', fields.get('byteskip', '0')))
    need = count * dtype.itemsize + max(0, skip)
    try:
        if encoding in ('gzip', 'gz', 'bzip2', 'bz2'):
            body = _inflate(body, encoding, need)
        if encoding in ('ascii', 'txt', 'text'):
            values = np.array(body.split()[:count], dtype=np.float64)
        elif encoding in ('raw', 'gzip', 'gz', 'bzip2', 'bz2'):
            if skip < 0:
                skip = len(body) - count * dtype.itemsize
            if len(body) - max(0, skip) < count * dtype.itemsize:
                raise TextureImageError('NRRD data holds %d bytes of %d'
                                        % (len(body) - max(0, skip), count * dtype.itemsize))
            values = np.frombuffer(body, dtype, count, max(0, skip))
        else:
            raise TextureImageError('NRRD encoding %r is not read' % (encoding,))
    except (OSError, EOFError, ValueError) as err:
        raise TextureImageError('NRRD data unreadable: %s' % (err,)) from err
    if len(values) != count:
        raise TextureImageError('NRRD data holds %d values of %d' % (len(values), count))
    volume = values.reshape(depth, height, width, channels)
    return 'volume', [_bytes(volume)]


def nrrd_bytes(volume: np.ndarray, compress: bool = True) -> bytes:
    """A uint8 volume as an NRRD file, gzip-encoded where ``compress``

    ``volume`` is ``(depth, height, width)`` or ``(depth, height, width,
    channels)`` with one to four channels; :func:`read_nrrd` reads it back as
    the same array. The channels are written as the first axis, of kind
    ``vector``.
    """
    volume = np.asarray(volume)
    if volume.dtype != np.uint8:
        raise ValueError('only uint8 volumes are written, not %s' % (volume.dtype,))
    if volume.ndim == 3:
        volume = volume[..., None]
    if volume.ndim != 4 or not 1 <= volume.shape[3] <= 4:
        raise ValueError('a volume of (depth, height, width[, 1 to 4 channels]), not %r'
                         % (volume.shape,))
    depth, height, width, channels = volume.shape
    body = np.ascontiguousarray(volume).tobytes()
    if channels == 1:
        layout = 'dimension: 3\nsizes: %d %d %d\nkinds: domain domain domain\n' % (
            width, height, depth)
    else:
        layout = 'dimension: 4\nsizes: %d %d %d %d\nkinds: vector domain domain domain\n' % (
            channels, width, height, depth)
    if compress:
        body = gzip.compress(body, mtime=0)
    header = 'NRRD0004\ntype: uint8\n%sencoding: %s\n\n' % (
        layout, 'gzip' if compress else 'raw')
    return header.encode('ascii') + body


def _whole(text: str) -> int:
    """An NRRD header's integer, or 0 where it is not one"""
    try:
        return int(text)
    except ValueError:
        return 0


def _inflate(body: bytes, encoding: str, need: int) -> bytes:
    """``body`` decompressed, no further than the ``need`` bytes the header asked for

    A stream that would inflate past them is not decompressed past them.
    """
    if encoding in ('gzip', 'gz'):
        return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(body, need)
    return bz2.BZ2Decompressor().decompress(body, need)


def _bytes(values: np.ndarray) -> np.ndarray:
    """``values`` as uint8, scaled from their range where they are wider than a byte"""
    if values.dtype == np.uint8:
        return np.ascontiguousarray(values)
    floats = values.astype(np.float64)
    finite = floats[np.isfinite(floats)]
    if not len(finite):
        return np.zeros(values.shape, np.uint8)
    low, high = float(finite.min()), float(finite.max())
    span = high - low if high > low else 1.0
    scaled = np.nan_to_num((floats - low) * (255.0 / span), nan=0.0, posinf=255.0, neginf=0.0)
    return np.clip(np.round(scaled), 0, 255).astype(np.uint8)


# -- one entry point each ------------------------------------------------------

def read_cube(data: bytes) -> list[np.ndarray]:
    """Six faces from a DDS or KTX cube map, or from one picture of six faces

    A picture is laid out as :func:`cube_from_layout` reads. Raises
    :class:`TextureImageError` for anything else.
    """
    if is_dds(data) or is_ktx(data):
        kind, found = read_dds(data) if is_dds(data) else read_ktx(data)
        if kind == 'cube':
            return found
        if kind == 'image':
            return cube_from_layout(found[0])
        raise TextureImageError('a volume is not a cube map')
    return cube_from_layout(_picture(data))


def read_volume(data: bytes,
                fetch: Optional[Callable[[str], bytes]] = None) -> np.ndarray:
    """A volume from a DDS, KTX or NRRD file

    ``fetch`` reads an NRRD's detached data (:func:`read_nrrd`). A file
    holding a single picture is a volume one slice deep.
    """
    if is_nrrd(data):
        return read_nrrd(data, fetch)[1][0]
    if is_dds(data) or is_ktx(data):
        kind, found = read_dds(data) if is_dds(data) else read_ktx(data)
        if kind == 'volume':
            return found[0]
        if kind == 'image':
            return np.ascontiguousarray(found[0][None, ::-1])
        raise TextureImageError('a cube map is not a volume')
    picture = _picture(data)
    return np.ascontiguousarray(picture[None, ::-1])


def _picture(data: bytes) -> np.ndarray:
    """An ordinary picture PIL reads, as an ``(h, w, c)`` uint8 array, top row first"""
    import io  # noqa: PLC0415 kept with its one use
    from PIL import Image  # noqa: PLC0415 only pictures need it
    try:
        image: Image.Image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as err:
        raise TextureImageError('not a picture PIL reads: %s' % (err,)) from err
    if image.mode not in ('L', 'LA', 'RGB', 'RGBA'):
        image = image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info
                              else 'RGB')
    pixels = np.asarray(image)
    return pixels[..., None] if pixels.ndim == 2 else pixels


#: Where each face sits in a layout, as (column, row) in face-sized cells, in
#: GL's face order; and whether the face is turned half round (a vertical
#: cross's -Z, seen from behind).
_LAYOUTS: dict[tuple[int, int], tuple[tuple[tuple[int, int], ...], bool]] = {
    (4, 3): (((2, 1), (0, 1), (1, 0), (1, 2), (1, 1), (3, 1)), False),
    (3, 4): (((2, 1), (0, 1), (1, 0), (1, 2), (1, 1), (1, 3)), True),
    (6, 1): (((0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0)), False),
    (1, 6): (((0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5)), False),
    (3, 2): (((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)), False),
}


def cube_from_layout(picture: np.ndarray) -> list[np.ndarray]:
    """The six faces of a picture laid out as a cross, a strip or 3x2

    The layout is told from the picture's proportions:

    - 4:3, a horizontal cross: -X, +Z, +X, -Z across the middle row, +Y over
      +Z and -Y under it.
    - 3:4, a vertical cross: -X, +Z, +X across the second row, +Y over +Z,
      -Y and then -Z under it, -Z upside down.
    - 6:1 or 1:6, a strip: +X, -X, +Y, -Y, +Z, -Z.
    - 3:2: +X, -X, +Y on the top row, -Y, +Z, -Z under them.

    The faces are those of GL's cube, the view along each axis from inside.
    """
    height, width = picture.shape[:2]
    for (columns, rows), (cells, turned) in _LAYOUTS.items():
        if width * rows == height * columns and width % columns == 0:
            side = width // columns
            _check_size(side, side, 6)
            faces = []
            for index, (column, row) in enumerate(cells):
                face = picture[row * side:(row + 1) * side, column * side:(column + 1) * side]
                if turned and index == 5:
                    face = face[::-1, ::-1]
                faces.append(np.ascontiguousarray(face))
            return faces
    raise TextureImageError('a picture of %dx%d is not a cube layout (4:3, 3:4, 6:1, 1:6 or 3:2)'
                            % (width, height))
