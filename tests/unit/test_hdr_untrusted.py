"""What a Radiance HDR header is allowed to make the decoder do.

The panorama loader is a parser this project wrote, over bytes somebody else
did. Two numbers in the header say how big the picture is, and the decoder
allocates that before it has read a single scanline -- so a file of a hundred
bytes can ask for forty gigabytes. Pillow refuses that arithmetic for the
formats it decodes; this one is ours to refuse.

A header line is the other end of the same question: read a byte at a time
until a newline, and a file with no newline in it is read entirely, one byte at
a time, into memory.
"""

import io

import pytest

from OpenGLContext.loaders import hdr


def _file(resolution, body=b'', fmt=b'32-bit_rle_rgbe'):
    return io.BytesIO(b'#?RADIANCE\nFORMAT=' + fmt + b'\n\n' + resolution + b'\n' + body)


class TestHowBigAPictureMayClaimToBe:
    def test_an_ordinary_panorama_is_read(self):
        """A 1k equirectangular HDRI is 1024 x 512, and must stay readable."""
        width, height, _flip_x, _flip_y = hdr._parse_header(
            _file(b'-Y 512 +X 1024'))

        assert (width, height) == (1024, 512)

    def test_a_declaration_too_large_to_be_a_picture_is_refused(self):
        with pytest.raises(hdr.HDRError):
            hdr._parse_header(_file(b'-Y 100000 +X 100000'))

    def test_the_refusal_happens_before_anything_is_allocated(self):
        """The header is a hundred bytes; the allocation would be forty
        gigabytes. Nothing may be reserved on the strength of it."""
        with pytest.raises(hdr.HDRError):
            hdr.load_hdr(_file(b'-Y 100000 +X 100000'))

    def test_a_dimension_that_is_not_a_number_is_refused_as_a_bad_file(self):
        with pytest.raises(hdr.HDRError):
            hdr._parse_header(_file(b'-Y 512 +X notanumber'))

    def test_a_dimension_beyond_what_an_int_should_hold_is_refused(self):
        with pytest.raises(hdr.HDRError):
            hdr._parse_header(_file(b'-Y 99999999999999999999 +X 8'))

    def test_a_negative_dimension_is_still_refused(self):
        with pytest.raises(hdr.HDRError):
            hdr._parse_header(_file(b'-Y 0 +X 16'))


class TestAHeaderLineThatNeverEnds:
    def test_a_line_longer_than_any_header_line_is_refused(self):
        """Rather than read to the end of the file a byte at a time."""
        with pytest.raises(hdr.HDRError):
            hdr._readline(io.BytesIO(b'x' * (1 << 20)))

    def test_a_file_that_is_not_a_header_at_all_is_refused(self):
        with pytest.raises(hdr.HDRError):
            hdr._parse_header(io.BytesIO(b'#?RADIANCE' + b'x' * (1 << 20)))

    def test_an_ordinary_header_line_is_read(self):
        assert hdr._readline(io.BytesIO(b'FORMAT=32-bit_rle_rgbe\n')) == \
            'FORMAT=32-bit_rle_rgbe'

    def test_the_last_line_of_a_file_needs_no_newline(self):
        assert hdr._readline(io.BytesIO(b'tail')) == 'tail'
