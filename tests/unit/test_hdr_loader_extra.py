"""Extra coverage for the Radiance RGBE decoder: header edge cases, the malformed-
scanline error paths, old-style repeat runs, and the -X column flip.
"""
import io

import numpy as np
import pytest

from OpenGLContext.loaders import hdr


def _header(width, height, ay="-Y", ax="+X"):
    return ("#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n%s %d %s %d\n"
            % (ay, height, ax, width)).encode("ascii")


# --- header parsing -----------------------------------------------------------

def test_header_line_without_trailing_newline_at_eof():
    # Magic present but the stream ends mid-line -> _readline breaks on empty read,
    # then the missing FORMAT is reported.
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(b"#?RADIANCE")


def test_header_comment_lines_are_skipped():
    body = (b"#?RADIANCE\n"
            b"# a comment line\n"
            b"FORMAT=32-bit_rle_rgbe\n\n"
            b"-Y 1 +X 2\n"
            + bytes([128, 128, 128, 128]) * 2)   # 2 flat pixels
    img = hdr.load_hdr_bytes(body)
    assert img.shape == (1, 2, 3)


def test_resolution_line_wrong_field_count_rejected():
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 4 +X\n")


def test_resolution_line_bad_axis_letters_rejected():
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Z 4 +Q 4\n")


def test_non_positive_dimensions_rejected():
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 0 +X 4\n")


# --- new-style adaptive RLE error paths ---------------------------------------

def _new_rle_prefix(width):
    return bytes([2, 2, (width >> 8) & 0xFF, width & 0xFF])


def test_new_rle_truncated_scanline_rejected():
    # Prefix promises width 8 but no channel data follows.
    data = _header(8, 1) + _new_rle_prefix(8)
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(data)


def test_new_rle_truncated_run_rejected():
    # A run record (count > 128) with no value byte after it.
    data = _header(8, 1) + _new_rle_prefix(8) + bytes([128 + 4])
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(data)


def test_new_rle_run_overflow_rejected():
    # A run of 127 (count byte 255) on an 8-wide scanline overflows it.
    data = _header(8, 1) + _new_rle_prefix(8) + bytes([255, 5])
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(data)


def test_new_rle_bad_literal_run_rejected():
    # A literal record with count 0 is malformed.
    data = _header(8, 1) + _new_rle_prefix(8) + bytes([0])
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(data)


def test_new_rle_truncated_literal_rejected():
    # Literal record promises 8 bytes but only 3 follow.
    data = _header(8, 1) + _new_rle_prefix(8) + bytes([8, 1, 2, 3])
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(data)


# --- flat / old-style RLE -----------------------------------------------------

def test_flat_scanline_truncated_rejected():
    # width 4 flat, but only 2 pixels' worth of bytes present after the first read.
    data = _header(4, 1) + bytes([10, 20, 30, 128]) + bytes([1, 2, 3])
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(data)


def test_old_style_rle_repeat_marker_expands_run():
    # First pixel, then a (1,1,1,count) marker repeats it `count` times.
    first = bytes([100, 120, 140, 128])
    marker = bytes([1, 1, 1, 3])       # repeat the previous pixel 3 times
    tail = bytes([50, 60, 70, 128])    # final literal pixel -> total width 5
    data = _header(5, 1) + first + marker + tail
    img = hdr.load_hdr_bytes(data)
    assert img.shape == (1, 5, 3)
    # Pixels 0..3 are the repeated first pixel, pixel 4 is the tail.
    assert np.allclose(img[0, 0], img[0, 3])
    assert not np.allclose(img[0, 0], img[0, 4])


def test_old_style_rle_run_clamped_to_scanline_width():
    # A repeat count larger than the remaining width is clamped, not overrun.
    first = bytes([100, 120, 140, 128])
    marker = bytes([1, 1, 1, 200])     # 200 >> would overflow a width-3 line
    data = _header(3, 1) + first + marker
    img = hdr.load_hdr_bytes(data)
    assert img.shape == (1, 3, 3)
    assert np.allclose(img[0, 0], img[0, 2])   # clamped fill reaches the last column


# --- image-level errors and orientation ---------------------------------------

def test_truncated_image_data_at_row_rejected():
    # Row 0 decodes fully (2 flat pixels), but the row-1 scanline head is truncated.
    row0 = bytes([128, 128, 128, 128]) * 2         # width 2, two flat pixels
    data = _header(2, 2) + row0 + bytes([2, 2])     # only 2 bytes where 4 are needed
    with pytest.raises(hdr.HDRError):
        hdr.load_hdr_bytes(data)


def test_negative_x_axis_flips_columns():
    # "-X" reverses column order; the decoder flips it back.
    left = bytes([200, 0, 0, 128])     # bright red
    right = bytes([0, 0, 200, 128])    # bright blue
    # Stored right-to-left because of -X, so on disk: [right, left].
    data = (b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 -X 2\n" + right + left)
    img = hdr.load_hdr_bytes(data)
    assert img[0, 0, 0] > img[0, 0, 2]     # column 0 is red after the flip
    assert img[0, 1, 2] > img[0, 1, 0]     # column 1 is blue


def test_load_hdr_accepts_a_file_object():
    body = _header(2, 1) + bytes([128, 128, 128, 128]) * 2
    img = hdr.load_hdr(io.BytesIO(body))   # file-like source, not a path
    assert img.shape == (1, 2, 3)
