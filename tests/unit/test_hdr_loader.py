"""Unit tests for the Radiance RGBE (.hdr) decoder in OpenGLContext.loaders.hdr.

Pure numpy, no GL context required. Synthetic RGBE images are encoded three ways
(flat, old-style RLE, new-style adaptive RLE) and round-tripped through the
decoder; the RGBE<->float math is checked directly; and a genuine Poly Haven CC0
panorama is decoded when the network is reachable.
"""
import io
import math
import struct
import numpy as np
import pytest

from OpenGLContext.loaders import hdr


# -- synthetic RGBE encoders (test-only; the library only decodes) ------------

def float_to_rgbe(rgb):
    """Encode an (H,W,3) float array to (H,W,4) uint8 RGBE (Radiance convention)."""
    rgb = np.asarray(rgb, dtype=np.float64)
    out = np.zeros(rgb.shape[:2] + (4,), dtype=np.uint8)
    mx = rgb.max(axis=2)
    nz = mx > 1e-32
    frac, exp = np.frexp(mx[nz])            # mx = frac * 2**exp, frac in [0.5,1)
    scale = frac * 256.0 / mx[nz]
    rgb_nz = rgb[nz]
    out_nz = out[nz]
    out_nz[:, 0] = np.clip(rgb_nz[:, 0] * scale, 0, 255).astype(np.uint8)
    out_nz[:, 1] = np.clip(rgb_nz[:, 1] * scale, 0, 255).astype(np.uint8)
    out_nz[:, 2] = np.clip(rgb_nz[:, 2] * scale, 0, 255).astype(np.uint8)
    out_nz[:, 3] = (exp + 128).astype(np.uint8)
    out[nz] = out_nz
    return out


def _header(width, height):
    return (b'#?RADIANCE\n'
            b'FORMAT=32-bit_rle_rgbe\n'
            b'\n'
            + ('-Y %d +X %d\n' % (height, width)).encode('ascii'))


def encode_flat(rgb):
    """Flat (uncompressed) RGBE: four raw bytes per pixel."""
    h, w = rgb.shape[:2]
    rgbe = float_to_rgbe(rgb)
    return _header(w, h) + rgbe.tobytes()


def encode_new_rle(rgb):
    """New-style adaptive-RLE, all-literal runs (exercises the literal path)."""
    h, w = rgb.shape[:2]
    assert 8 <= w < 32768
    rgbe = float_to_rgbe(rgb)
    body = bytearray()
    for y in range(h):
        body += bytes([2, 2, (w >> 8) & 0xff, w & 0xff])
        for ch in range(4):
            chan = rgbe[y, :, ch]
            x = 0
            while x < w:
                n = min(128, w - x)
                body.append(n)                     # literal run of n
                body += chan[x:x + n].tobytes()
                x += n
    return _header(w, h) + bytes(body)


def encode_new_rle_runs(rgb):
    """New-style adaptive-RLE using genuine repeat runs (exercises the run path)."""
    h, w = rgb.shape[:2]
    rgbe = float_to_rgbe(rgb)
    body = bytearray()
    for y in range(h):
        body += bytes([2, 2, (w >> 8) & 0xff, w & 0xff])
        for ch in range(4):
            chan = rgbe[y, :, ch]
            x = 0
            while x < w:
                run = 1
                while x + run < w and chan[x + run] == chan[x] and run < 127:
                    run += 1
                if run > 1:
                    body.append(128 + run)         # repeat next byte `run` times
                    body.append(int(chan[x]))
                    x += run
                else:
                    body.append(1)                 # single literal
                    body.append(int(chan[x]))
                    x += 1
    return _header(w, h) + bytes(body)


def encode_old_rle(rgb):
    """Old-style RLE with (1,1,1,count) repeat markers."""
    h, w = rgb.shape[:2]
    rgbe = float_to_rgbe(rgb)
    body = bytearray()
    for y in range(h):
        x = 0
        while x < w:
            body += rgbe[y, x].tobytes()
            run = 0
            while (x + 1 + run < w
                   and np.array_equal(rgbe[y, x + 1 + run], rgbe[y, x])
                   and run < 255):
                run += 1
            if run > 0:
                body += bytes([1, 1, 1, run])
                x += 1 + run
            else:
                x += 1
    return _header(w, h) + bytes(body)


# -- fixtures -----------------------------------------------------------------

def _gradient(h, w):
    """A smooth HDR gradient with values spanning well above 1.0."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = (xx / max(1, w - 1)) * 8.0            # up to 8.0 (HDR)
    g = (yy / max(1, h - 1)) * 2.0
    b = np.full((h, w), 0.25, dtype=np.float32)
    return np.stack([r, g, b], axis=-1).astype(np.float32)


def _assert_close_rgbe(decoded, original):
    """Compare within RGBE quantisation error (relative, ~1/256 per pixel)."""
    tol = original.max() / 256.0 * 2 + 1e-3
    assert decoded.shape == original.shape
    assert np.max(np.abs(decoded - original)) < tol


# -- tests --------------------------------------------------------------------

def test_rgbe_to_float_known_values():
    # exponent 128 => 2**0, mantissa m/256
    rgbe = np.array([[128, 64, 0, 128]], dtype=np.uint8)
    out = hdr.rgbe_to_float(rgbe)
    assert out.shape == (1, 3)
    assert abs(out[0, 0] - 128 / 256.0) < 1e-6
    assert abs(out[0, 1] - 64 / 256.0) < 1e-6
    assert out[0, 2] == 0.0


def test_rgbe_zero_exponent_is_black():
    rgbe = np.array([[200, 200, 200, 0]], dtype=np.uint8)
    out = hdr.rgbe_to_float(rgbe)
    assert np.all(out == 0.0)


def test_rgbe_exponent_scales_by_power_of_two():
    lo = hdr.rgbe_to_float(np.array([[128, 128, 128, 128]], dtype=np.uint8))
    hi = hdr.rgbe_to_float(np.array([[128, 128, 128, 129]], dtype=np.uint8))
    assert np.allclose(hi, lo * 2.0)


@pytest.mark.parametrize('encoder', [
    encode_flat, encode_new_rle, encode_new_rle_runs, encode_old_rle])
def test_roundtrip_encodings(encoder):
    original = _gradient(24, 40)
    data = encoder(original)
    decoded = hdr.load_hdr_bytes(data)
    _assert_close_rgbe(decoded, original)


def test_flat_narrow_image_below_rle_threshold():
    # width < 8 must use the flat path even though bytes could look like a prefix.
    original = _gradient(4, 5)
    decoded = hdr.load_hdr_bytes(encode_flat(original))
    _assert_close_rgbe(decoded, original)


def test_orientation_top_row_first():
    # Top row (y=0) is darker in green than the bottom row in the gradient.
    original = _gradient(16, 16)
    decoded = hdr.load_hdr_bytes(encode_new_rle(original))
    assert decoded[0].mean() < decoded[-1].mean()


def test_flip_y_positive_sign():
    original = _gradient(8, 16)
    rgbe = float_to_rgbe(original)
    # "+Y" resolution => stored bottom-up; decoder must flip back to top-first.
    body = (b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n'
            + ('+Y %d +X %d\n' % (8, 16)).encode('ascii')
            + rgbe[::-1].tobytes())
    decoded = hdr.load_hdr_bytes(body)
    _assert_close_rgbe(decoded, original)


def test_bad_magic_rejected():
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(b'PNG not a radiance file\n\n')


def test_missing_format_rejected():
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(b'#?RADIANCE\n\n-Y 4 +X 4\n' + b'\0' * 64)


def test_unsupported_format_rejected():
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(b'#?RADIANCE\nFORMAT=float\n\n-Y 2 +X 2\n')


def test_truncated_data_rejected():
    original = _gradient(8, 16)
    data = encode_new_rle(original)[:-40]
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(data)


def test_real_polyhaven_hdr_if_available():
    """Decode a genuine Poly Haven CC0 panorama (skips if offline)."""
    from OpenGLContext.loaders.resolver import fetch_to_cache
    url = ('https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/'
           'studio_small_03_1k.hdr')
    try:
        path = fetch_to_cache(url)
    except Exception as err:                       # network unavailable in CI
        pytest.skip('network unavailable: %s' % err)
    img = hdr.load_hdr(path)
    assert img.ndim == 3 and img.shape[2] == 3
    assert img.shape[0] * 2 == img.shape[1]        # equirectangular 2:1
    assert img.dtype == np.float32
    assert img.max() > 1.0                         # genuine HDR range
    assert np.all(np.isfinite(img))


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
