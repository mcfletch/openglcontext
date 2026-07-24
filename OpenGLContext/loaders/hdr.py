"""Radiance RGBE (``.hdr`` / ``.pic``) high-dynamic-range image decoder.

Radiance's RGBE format stores a floating-point radiance image compactly: each
pixel is four bytes -- red, green, blue mantissas and one shared exponent -- so a
single 8-bit exponent gives the whole pixel its dynamic range. It is the common
interchange format for the HDRI environment panoramas (Poly Haven, HDRI Haven,
sIBL archives) used as image-based-lighting sources, so decoding it lets those
panoramas drive :mod:`OpenGLContext.passes.ibl` and the HDR skybox background.

:func:`load_hdr` returns an ``(H, W, 3)`` ``float32`` array of **linear** radiance
(RGBE is already linear -- no sRGB decode). numpy is a hard dependency of
OpenGLContext, so the decode is fully vectorised and needs no GL context, which
also makes it unit-testable headless.

The decoder handles the three scanline encodings Radiance emits:

* **new-style adaptive RLE** -- each scanline is prefixed ``2 2 hi lo`` (width =
  ``hi<<8 | lo``) and its four channels are run-length encoded separately;
* **old-style RLE** -- ``1 1 1 count`` repeat records shared across channels;
* **flat** -- four raw bytes per pixel, no compression.
"""
from __future__ import annotations

from typing import BinaryIO, Union, cast

import numpy as np

__all__ = ['load_hdr', 'load_hdr_bytes', 'rgbe_to_float']


class HDRError(ValueError):
    """A file that is not a well-formed Radiance RGBE image."""


def _readline(fh: BinaryIO) -> str:
    """Read one newline-terminated header line as ``str`` (headers are ASCII)."""
    buf = bytearray()
    while True:
        ch = fh.read(1)
        if not ch:
            break
        if ch == b'\n':
            break
        buf += ch
    return buf.decode('latin-1')


def _parse_header(fh: BinaryIO) -> tuple[int, int, bool, bool]:
    """Consume the Radiance header, returning ``(width, height, flip_x, flip_y)``.

    Leaves ``fh`` positioned at the first scanline byte. Raises :class:`HDRError`
    if the magic, ``FORMAT`` or resolution line is missing or unsupported.
    """
    magic = _readline(fh)
    if not magic.startswith('#?'):
        raise HDRError('not a Radiance HDR file (bad magic %r)' % magic[:16])
    fmt = None
    while True:
        line = _readline(fh)
        if line == '':          # blank line terminates the header
            break
        if line.startswith('#'):
            continue
        key, _, value = line.partition('=')
        if key.strip().upper() == 'FORMAT':
            fmt = value.strip()
    if fmt is None:
        raise HDRError('Radiance HDR header missing FORMAT')
    if fmt not in ('32-bit_rle_rgbe', '32-bit_rle_xyze'):
        raise HDRError('unsupported Radiance FORMAT %r' % fmt)

    # Resolution line, e.g. "-Y 512 +X 1024". The signs give scan direction; the
    # standard/overwhelmingly-common orientation is "-Y H +X W" (rows top-to-bottom,
    # columns left-to-right). Support the sign variants so rotated exports decode
    # right-side up.
    res = _readline(fh)
    parts = res.split()
    if len(parts) != 4:
        raise HDRError('bad Radiance resolution line %r' % res)
    ay, ny, ax, nx = parts
    if ay[1:] not in ('Y', 'X') or ax[1:] not in ('Y', 'X'):
        raise HDRError('bad Radiance resolution line %r' % res)
    height = int(ny)
    width = int(nx)
    if width <= 0 or height <= 0:
        raise HDRError('non-positive Radiance dimensions %dx%d' % (width, height))
    # "-Y" means the first scanline is the top row (no vertical flip needed to get
    # a top-to-bottom array); "+Y" means bottom-up, so flip. Likewise "-X" flips
    # columns.
    flip_y = ay.startswith('+')
    flip_x = ax.startswith('-')
    return width, height, flip_x, flip_y


def _decode_new_rle(fh: BinaryIO, width: int) -> np.ndarray:
    """Decode one new-style adaptive-RLE scanline into a ``(width, 4)`` uint8 row.

    ``fh`` is positioned just after the ``2 2 hi lo`` prefix. Each of the four
    channels is stored contiguously as a mix of run records (count > 128: repeat
    the next byte ``count-128`` times) and literal records (count <= 128: copy the
    next ``count`` bytes).
    """
    row = np.empty((4, width), dtype=np.uint8)
    for ch in range(4):
        x = 0
        while x < width:
            b = fh.read(1)
            if not b:
                raise HDRError('truncated RGBE scanline')
            count = b[0]
            if count > 128:
                n = count - 128
                val = fh.read(1)
                if not val:
                    raise HDRError('truncated RGBE run')
                if x + n > width:
                    raise HDRError('RGBE run overflows scanline')
                row[ch, x:x + n] = val[0]
                x += n
            else:
                n = count
                if n == 0 or x + n > width:
                    raise HDRError('bad RGBE literal run')
                data = fh.read(n)
                if len(data) != n:
                    raise HDRError('truncated RGBE literal')
                row[ch, x:x + n] = np.frombuffer(data, dtype=np.uint8)
                x += n
    return row.T.copy()   # (width, 4)


def _decode_flat_or_old_rle(fh: BinaryIO, first4: bytes, width: int) -> np.ndarray:
    """Decode a flat / old-RLE scanline given its already-read first pixel.

    Old-style RLE marks a repeat with an ``(1, 1, 1, count)`` pixel: the previous
    pixel is repeated ``count`` times (``count`` shifted left by 8 for each further
    consecutive marker, so long runs chain). Anything else is a literal pixel.
    """
    row = np.empty((width, 4), dtype=np.uint8)
    prev = np.frombuffer(first4, dtype=np.uint8)
    row[0] = prev
    x = 1
    shift = 0
    while x < width:
        px = fh.read(4)
        if len(px) != 4:
            raise HDRError('truncated flat RGBE scanline')
        arr = np.frombuffer(px, dtype=np.uint8)
        if arr[0] == 1 and arr[1] == 1 and arr[2] == 1:
            n = int(arr[3]) << shift
            if x + n > width:
                n = width - x
            row[x:x + n] = prev
            x += n
            shift += 8
        else:
            row[x] = arr
            prev = arr
            x = x + 1
            shift = 0
    return row


def _decode_scanlines(fh: BinaryIO, width: int, height: int) -> np.ndarray:
    """Decode all ``height`` scanlines into a ``(height, width, 4)`` uint8 array."""
    out = np.empty((height, width, 4), dtype=np.uint8)
    # New-style adaptive RLE is only used for 8 <= width < 32768; narrower or wider
    # scanlines are always flat/old-RLE. The per-scanline prefix disambiguates.
    for y in range(height):
        head = fh.read(4)
        if len(head) != 4:
            raise HDRError('truncated RGBE image data at row %d' % y)
        if (head[0] == 2 and head[1] == 2
                and (head[2] << 8 | head[3]) == width
                and 8 <= width < 32768):
            out[y] = _decode_new_rle(fh, width)
        else:
            out[y] = _decode_flat_or_old_rle(fh, head, width)
    return out


def rgbe_to_float(rgbe: np.ndarray) -> np.ndarray:
    """Convert an ``(..., 4)`` uint8 RGBE array to ``(..., 3)`` float32 radiance.

    A pixel with exponent byte ``e`` and mantissa byte ``m`` decodes to
    ``m / 256 * 2**(e - 128)`` (i.e. ``m * 2**(e - 136)``); a zero exponent is
    exact black. This matches the common graphics-pipeline decoders (stb_image's
    HDR loader, Bruce Walter's ``rgbe.c``) rather than Ward's half-step-biased
    variant, so a zero mantissa is exactly zero and results line up with what
    glTF/IBL reference renderers expect.
    """
    rgbe = np.asarray(rgbe, dtype=np.uint8)
    mant = rgbe[..., :3].astype(np.float32)
    exp = rgbe[..., 3].astype(np.int32)
    scale = np.ldexp(1.0, exp - (128 + 8)).astype(np.float32)   # 2**(e-136)
    out = mant * scale[..., np.newaxis]
    out[exp == 0] = 0.0
    return np.ascontiguousarray(out, dtype=np.float32)


def _load(fh: BinaryIO) -> np.ndarray:
    width, height, flip_x, flip_y = _parse_header(fh)
    rgbe = _decode_scanlines(fh, width, height)
    img = rgbe_to_float(rgbe)
    if flip_y:
        img = img[::-1]
    if flip_x:
        img = img[:, ::-1]
    return np.ascontiguousarray(img, dtype=np.float32)


def load_hdr(source: Union[str, BinaryIO]) -> np.ndarray:
    """Load a Radiance ``.hdr``/``.pic`` image as an ``(H, W, 3)`` float32 array.

    ``source`` is a filesystem path or an already-open binary file object. The
    returned radiance is linear (no sRGB decode), top row first, and may contain
    values well above 1.0 -- that dynamic range is the whole point of the format.
    """
    if hasattr(source, 'read'):
        return _load(cast(BinaryIO, source))
    with open(cast(str, source), 'rb') as fh:
        return _load(fh)


def load_hdr_bytes(data: bytes) -> np.ndarray:
    """Load a Radiance HDR image from an in-memory ``bytes`` buffer."""
    import io
    return _load(io.BytesIO(data))
