"""A texture that cannot be decoded costs the texture, not the scene.

An ``ImageTexture`` names a file somebody else wrote. It may be truncated, it
may not be an image at all, and it may be a few dozen bytes that declare a
billion pixels -- the classic decompression bomb, which Pillow refuses to
decode. A world with one bad texture in it is a world that should draw with one
texture missing, so every one of those is a warning and an unset image rather
than an exception out of the load.

No GL: this is the decode, not the upload.
"""

import struct
import zlib
import io

import pytest
from PIL import Image

from OpenGLContext.scenegraph import basenodes


def _png(width, height, payload=None):
    """A PNG whose header declares ``width`` x ``height``.

    The declaration is what a reader allocates against, and it costs the file
    eight bytes to make -- which is the whole of why a bomb is cheap to send.
    """
    def chunk(tag, data):
        raw = tag + data
        return struct.pack('>I', len(data)) + raw + struct.pack('>I', zlib.crc32(raw))
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(payload or b'\0')) + chunk(b'IEND', b''))


@pytest.fixture
def real_png(tmp_path):
    path = tmp_path / 'ok.png'
    Image.new('RGB', (4, 4), (10, 200, 30)).save(str(path))
    return str(path)


@pytest.fixture
def bomb(tmp_path):
    """Sixty-six bytes claiming nine hundred million pixels."""
    path = tmp_path / 'bomb.png'
    path.write_bytes(_png(30000, 30000))
    return str(path)


@pytest.fixture
def rubbish(tmp_path):
    path = tmp_path / 'rubbish.png'
    path.write_bytes(b'not a png at all, just some bytes')
    return str(path)


class TestLoadingFromAUrl:
    def test_an_ordinary_image_loads(self, real_png):
        texture = basenodes.ImageTexture()

        texture.loadBackground([real_png])

        assert texture.image is not None
        assert texture.image.size == (4, 4)

    def test_a_decompression_bomb_is_refused(self, bomb, caplog):
        texture = basenodes.ImageTexture()

        texture.loadBackground([bomb])

        assert not texture.image
        assert 'bomb.png' in caplog.text

    def test_rubbish_is_refused(self, rubbish, caplog):
        texture = basenodes.ImageTexture()

        texture.loadBackground([rubbish])

        assert not texture.image
        assert 'rubbish.png' in caplog.text

    def test_a_missing_file_is_still_only_a_warning(self, tmp_path, caplog):
        texture = basenodes.ImageTexture()

        texture.loadBackground([str(tmp_path / 'absent.png')])

        assert not texture.image

    def test_the_first_url_that_works_is_used(self, bomb, real_png):
        """VRML97 lists alternatives; a bad one must not end the list."""
        texture = basenodes.ImageTexture()

        texture.loadBackground([bomb, real_png])

        assert texture.image is not None
        assert texture.image.size == (4, 4)


class TestLoadingFromBytes:
    def test_ordinary_bytes_load(self):

        held = io.BytesIO()
        Image.new('RGB', (2, 2), (1, 2, 3)).save(held, format='PNG')
        texture = basenodes.ImageTexture()

        texture.loadFromData(held.getvalue())

        assert texture.image.size == (2, 2)

    def test_a_decompression_bomb_is_refused(self, caplog):
        texture = basenodes.ImageTexture()

        texture.loadFromData(_png(30000, 30000))

        assert not texture.image

    def test_rubbish_is_refused(self):
        texture = basenodes.ImageTexture()

        texture.loadFromData(b'nothing like an image')

        assert not texture.image
