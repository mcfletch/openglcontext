"""Cube maps and volumes read from DDS, KTX, NRRD and laid-out pictures

The files are written here byte by byte from the formats' published layouts,
so each test says what a file holds and checks what was read from it.
"""
import gzip
import io
import struct

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.loaders import textureimages
from OpenGLContext.loaders.textureimages import TextureImageError

#: A distinct colour for each cube face, in GL's order.
FACE_COLOURS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]


def dds(width, height, payload, *, depth=0, fourcc=b'', bits=32,
        masks=(0xFF0000, 0xFF00, 0xFF, 0xFF000000), cube=False, flags=0x41, dx10=None):
    """A DDS file: the magic, the 124-byte header and ``payload``"""
    caps2 = (0x200 | 0xFC00) if cube else (0x200000 if depth else 0)
    header_flags = 0x1007 | (0x800000 if depth else 0)
    pixel_flags = 0x4 if fourcc else flags
    header = struct.pack('<7I', 124, header_flags, height, width, 0, depth, 1)
    header += b'\0' * 44
    header += struct.pack('<2I4s5I', 32, pixel_flags, fourcc or b'\0\0\0\0', bits, *masks)
    header += struct.pack('<4I', 0x1000, caps2, 0, 0) + b'\0' * 4
    extra = struct.pack('<5I', *dx10) if dx10 else b''
    return b'DDS ' + header + extra + payload


def bgra(colour, count, alpha=255):
    red, green, blue = colour
    return bytes([blue, green, red, alpha]) * count


def test_a_dds_cube_map_gives_six_faces_in_gl_order():
    payload = b''.join(bgra(colour, 4) for colour in FACE_COLOURS)
    faces = textureimages.read_cube(dds(2, 2, payload, cube=True))
    assert len(faces) == 6
    for face, colour in zip(faces, FACE_COLOURS):
        assert face.shape == (2, 2, 4)
        assert tuple(face[0, 0, :3]) == colour


def test_a_dds_cube_map_missing_a_face_is_refused():
    data = bytearray(dds(2, 2, bgra((1, 2, 3), 4 * 6), cube=True))
    data[112:116] = struct.pack('<I', 0x200 | 0x7C00)
    with pytest.raises(TextureImageError, match='5 faces'):
        textureimages.read_cube(bytes(data))


def test_a_dds_volume_gives_its_slices_bottom_row_first():
    # Two slices of 1x2: each slice's top row red, bottom row blue.
    rows = bgra((255, 0, 0), 1) + bgra((0, 0, 255), 1)
    volume = textureimages.read_volume(dds(1, 2, rows * 2, depth=2))
    assert volume.shape == (2, 2, 1, 4)
    assert tuple(volume[0, 0, 0, :3]) == (0, 0, 255)
    assert tuple(volume[1, 1, 0, :3]) == (255, 0, 0)


def test_a_dds_of_dxt1_blocks_is_decoded():
    block = bytes([0x00, 0xF8, 0x1F, 0x00, 0, 0, 0, 0])     # all colour0: red
    kind, found = textureimages.read_dds(dds(4, 4, block, fourcc=b'DXT1'))
    assert kind == 'image'
    assert tuple(found[0][0, 0]) == (255, 0, 0, 255)


def test_a_dds_dx10_cube_map_of_rgba_bytes():
    payload = b''.join(bytes(colour + (255,)) * 1 for colour in FACE_COLOURS)
    data = dds(1, 1, payload, fourcc=b'DX10', dx10=(28, 3, 0x4, 1, 0))
    faces = textureimages.read_cube(data)
    assert [tuple(face[0, 0, :3]) for face in faces] == FACE_COLOURS


def test_a_dds_of_luminance_bytes():
    data = dds(2, 1, bytes([10, 200]), bits=8, masks=(0xFF, 0, 0, 0), flags=0x20000)
    kind, found = textureimages.read_dds(data)
    assert found[0].shape == (1, 2, 1)
    assert list(found[0][0, :, 0]) == [10, 200]


def test_a_dds_of_five_six_five_pixels_scales_each_channel():
    data = dds(1, 1, struct.pack('<H', 0xF800), bits=16, masks=(0xF800, 0x7E0, 0x1F, 0),
               flags=0x40)
    assert tuple(textureimages.read_dds(data)[1][0][0, 0]) == (255, 0, 0)


@pytest.mark.parametrize('data, message', [
    (b'DDS ' + b'\0' * 10, 'not a DDS'),
    (dds(2, 2, b'\0' * 3, cube=False), 'cut short'),
    (dds(4, 4, b'', fourcc=b'ATI2'), 'not read'),
    (dds(70000, 70000, b''), 'allowed'),
])
def test_a_dds_that_does_not_hold_what_it_says_is_refused(data, message):
    with pytest.raises(TextureImageError, match=message):
        textureimages.read_dds(data)


def ktx(width, height, images, *, gl_format=0x1908, internal=0x8058, gl_type=0x1401,
        faces=1, depth=0):
    """A KTX 1.1 file of ``images``, each one face or slice, rows unpadded here"""
    header = struct.pack('<13I', 0x04030201, gl_type, 1, gl_format, internal, gl_format,
                         width, height, depth, 0, faces, 1, 0)
    body = struct.pack('<I', len(images[0]))
    for image in images:
        body += image + b'\0' * ((-len(image)) % 4)
    return b'\xabKTX 11\xbb\r\n\x1a\n' + header + body


def test_a_ktx_cube_map_gives_six_faces():
    images = [bytes(colour + (255,)) * 4 for colour in FACE_COLOURS]
    faces = textureimages.read_cube(ktx(2, 2, images, faces=6))
    assert [tuple(face[1, 1, :3]) for face in faces] == FACE_COLOURS


def test_a_ktx_rgb_image_pads_its_rows_to_four_bytes():
    # 1x2 RGB: each 3-byte row is padded to 4.
    image = bytes([255, 0, 0, 0, 0, 0, 255, 0])
    kind, found = textureimages.read_ktx(ktx(1, 2, [image], gl_format=0x1907))
    assert kind == 'image'
    # The first row in the file is t=0, the picture's bottom.
    assert tuple(found[0][1, 0]) == (255, 0, 0)
    assert tuple(found[0][0, 0]) == (0, 0, 255)


def test_a_ktx_volume():
    slices = [bytes([value] * 8) for value in (10, 20, 30)]
    volume = textureimages.read_volume(ktx(4, 2, slices, gl_format=0x1909, depth=3))
    assert volume.shape == (3, 2, 4, 1)
    assert list(volume[:, 0, 0, 0]) == [10, 20, 30]


def test_a_ktx_of_another_type_is_refused():
    with pytest.raises(TextureImageError, match='not read'):
        textureimages.read_ktx(ktx(1, 1, [b'\0' * 8], gl_type=0x1406))


def nrrd(header, body):
    return b'NRRD0004\n' + header.encode('latin-1') + b'\n' + body


def test_an_nrrd_volume_of_bytes():
    body = bytes(range(24))
    volume = textureimages.read_volume(nrrd(
        'type: uchar\ndimension: 3\nsizes: 4 3 2\nencoding: raw\n', body))
    assert volume.shape == (2, 3, 4, 1)
    assert volume[1, 2, 3, 0] == 23
    assert volume[0, 1, 0, 0] == 4


def test_an_nrrd_of_shorts_is_scaled_from_its_range_to_bytes():
    values = np.array([0, 100, 400, 0], '<i2')
    volume = textureimages.read_volume(nrrd(
        'type: short\ndimension: 3\nsizes: 2 2 1\nendian: little\nencoding: gzip\n',
        gzip.compress(values.tobytes())))
    assert list(volume.ravel()) == [0, 64, 255, 0]


def test_an_nrrd_of_four_dimensions_has_its_channels_first():
    body = bytes([255, 0, 0, 0, 255, 0])
    volume = textureimages.read_volume(nrrd(
        'type: uint8\ndimension: 4\nsizes: 3 2 1 1\nencoding: raw\n', body))
    assert volume.shape == (1, 1, 2, 3)
    assert tuple(volume[0, 0, 1]) == (0, 255, 0)


def test_an_nrrd_of_three_axes_whose_first_kind_is_a_colour_has_channels():
    volume = textureimages.read_volume(nrrd(
        'type: uint8\ndimension: 3\nsizes: 2 2 1\nkinds: 2-vector domain domain\n'
        'encoding: raw\n', bytes([1, 2, 3, 4])))
    assert volume.shape == (1, 1, 2, 2)


def test_an_nrrd_reads_its_detached_data_through_the_fetch_it_is_given():
    asked = []

    def fetch(name):
        asked.append(name)
        return bytes([7, 8])
    volume = textureimages.read_volume(nrrd(
        'type: uchar\ndimension: 2\nsizes: 2 1\nencoding: raw\ndata file: values.raw\n', b''),
        fetch)
    assert asked == ['values.raw']
    assert list(volume.ravel()) == [7, 8]


@pytest.mark.parametrize('header, message', [
    ('type: quaternion\ndimension: 3\nsizes: 1 1 1\n', 'type'),
    ('type: uchar\ndimension: 1\nsizes: 4\n', 'dimensions'),
    ('type: uchar\ndimension: 3\nsizes: 2 2 2\nencoding: raw\n', 'holds'),
    ('type: uchar\ndimension: 2\nsizes: 1 1\nencoding: zip\n', 'encoding'),
    ('type: uchar\ndimension: 2\nsizes: 1 1\ndata file: elsewhere\n', 'elsewhere'),
])
def test_an_nrrd_that_does_not_hold_what_it_says_is_refused(header, message):
    with pytest.raises(TextureImageError, match=message):
        textureimages.read_nrrd(nrrd(header, b'\1'))


def picture(cells, layout):
    """A PNG of 2x2-pixel cells, ``cells`` giving each face's (column, row)"""
    columns, rows = layout
    image = np.zeros((rows * 2, columns * 2, 3), np.uint8)
    for (column, row), colour in zip(cells, FACE_COLOURS):
        image[row * 2:row * 2 + 2, column * 2:column * 2 + 2] = colour
    stream = io.BytesIO()
    Image.fromarray(image).save(stream, 'PNG')
    return stream.getvalue()


@pytest.mark.parametrize('layout, cells', [
    ((4, 3), [(2, 1), (0, 1), (1, 0), (1, 2), (1, 1), (3, 1)]),
    ((3, 4), [(2, 1), (0, 1), (1, 0), (1, 2), (1, 1), (1, 3)]),
    ((6, 1), [(index, 0) for index in range(6)]),
    ((1, 6), [(0, index) for index in range(6)]),
    ((3, 2), [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)]),
])
def test_a_picture_of_six_faces_is_read_by_its_proportions(layout, cells):
    faces = textureimages.read_cube(picture(cells, layout))
    assert [tuple(face[0, 0, :3]) for face in faces] == FACE_COLOURS


def test_a_vertical_cross_turns_its_back_face_round():
    image = np.zeros((8, 6, 3), np.uint8)
    image[6, 2] = (255, 255, 255)           # -Z's top left, as the cross holds it
    faces = textureimages.cube_from_layout(image)
    assert tuple(faces[5][1, 1]) == (255, 255, 255)


def test_a_picture_of_other_proportions_is_no_cube():
    with pytest.raises(TextureImageError, match='cube layout'):
        textureimages.cube_from_layout(np.zeros((5, 7, 3), np.uint8))


def test_a_picture_is_a_volume_one_slice_deep_bottom_row_first():
    image = np.zeros((2, 1, 3), np.uint8)
    image[0, 0] = (255, 0, 0)
    stream = io.BytesIO()
    Image.fromarray(image).save(stream, 'PNG')
    volume = textureimages.read_volume(stream.getvalue())
    assert volume.shape == (1, 2, 1, 3)
    assert tuple(volume[0, 1, 0]) == (255, 0, 0)


def test_bytes_that_are_no_picture_are_refused():
    with pytest.raises(TextureImageError, match='PIL'):
        textureimages.read_volume(b'not an image at all')
