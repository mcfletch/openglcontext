"""X3D's Texturing3D textures: the volume each node holds

PixelTexture3D's pixels, ComposedTexture3D's slices and ImageTexture3D's
file come out as one ``(depth, height, width, channels)`` volume, with r=0
the first slice and t=0 the first row.
"""
import struct

import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import texture3d


def test_a_pixel_texture_3d_unpacks_its_pixels_s_then_t_then_r():
    texture = texture3d.PixelTexture3D(
        image=[3, 2, 1, 2, 0xFF0000, 0x00FF00, 0x0000FF, 0xFFFFFF])
    volume = texture.volumeData()
    assert volume.shape == (2, 1, 2, 3)
    assert tuple(volume[0, 0, 1]) == (0, 255, 0)
    assert tuple(volume[1, 0, 0]) == (0, 0, 255)


@pytest.mark.parametrize('image', [[0, 0, 0, 0], [1, 2, 2, 2, 1, 2], [9, 1, 1, 1, 0]])
def test_a_pixel_texture_3d_that_does_not_hold_its_pixels_has_no_volume(image):
    assert texture3d.PixelTexture3D(image=image).volumeData() is None


def test_a_pixel_texture_3d_volume_follows_its_image():
    texture = texture3d.PixelTexture3D(image=[1, 1, 1, 1, 0x40])
    assert texture.volumeData()[0, 0, 0, 0] == 0x40
    texture.image = [1, 1, 1, 1, 0x80]
    assert texture.volumeData()[0, 0, 0, 0] == 0x80


def slice_texture(colour):
    return x3d.PixelTexture(image=[2, 1, 3] + [colour] * 2)


def test_a_composed_texture_3d_stacks_its_textures_as_slices():
    texture = texture3d.ComposedTexture3D(
        texture=[slice_texture(0xFF0000), slice_texture(0x0000FF)])
    volume = texture.volumeData()
    assert volume.shape == (2, 1, 2, 3)
    assert tuple(volume[0, 0, 0]) == (255, 0, 0)
    assert tuple(volume[1, 0, 1]) == (0, 0, 255)


def test_a_composed_texture_3d_resamples_slices_to_the_first_ones_size():
    big = x3d.PixelTexture(image=[4, 2, 1] + [0x80] * 8)
    texture = texture3d.ComposedTexture3D(texture=[slice_texture(0xFF0000), big])
    volume = texture.volumeData()
    assert volume.shape == (2, 1, 2, 3)
    assert tuple(volume[1, 0, 0]) == (0x80, 0x80, 0x80)


def test_a_composed_texture_3d_follows_a_slice_changing():
    first = slice_texture(0xFF0000)
    texture = texture3d.ComposedTexture3D(texture=[first])
    assert tuple(texture.volumeData()[0, 0, 0]) == (255, 0, 0)
    first.image = [2, 1, 3, 0x00FF00, 0x00FF00]
    assert tuple(texture.volumeData()[0, 0, 0]) == (0, 255, 0)


def test_a_composed_texture_3d_of_no_loaded_slice_has_no_volume():
    assert texture3d.ComposedTexture3D(texture=[]).volumeData() is None


def nrrd_file(tmp_path, name='volume.nrrd'):
    path = tmp_path / name
    path.write_bytes(b'NRRD0004\ntype: uchar\ndimension: 3\nsizes: 2 2 2\n'
                     b'encoding: raw\n\n' + bytes(range(8)))
    return path


def test_an_image_texture_3d_reads_its_url(tmp_path):
    texture = texture3d.ImageTexture3D()
    texture.loadBackground([str(nrrd_file(tmp_path))])
    volume = texture.volumeData()
    assert volume.shape == (2, 2, 2, 1)
    assert volume[1, 1, 1, 0] == 7
    assert (texture.width, texture.height, texture.depth, texture.colorDepth) == (2, 2, 2, 1)
    from vrml.x3d import loadsensor  # noqa: PLC0415 kept with its use
    assert loadsensor.load_state(texture) == loadsensor.LOADED


def test_an_image_texture_3d_reads_an_nrrds_detached_data_beside_it(tmp_path):
    (tmp_path / 'values.raw').write_bytes(bytes([5, 6]))
    header = tmp_path / 'detached.nhdr'
    header.write_bytes(b'NRRD0004\ntype: uchar\ndimension: 2\nsizes: 2 1\n'
                       b'encoding: raw\ndata file: values.raw\n\n')
    texture = texture3d.ImageTexture3D()
    texture.loadBackground([str(header)])
    assert list(texture.volumeData().ravel()) == [5, 6]


def test_an_image_texture_3d_of_nothing_readable_fails(tmp_path):
    bad = tmp_path / 'bad.nrrd'
    bad.write_bytes(b'NRRD0004\ntype: uchar\n')
    texture = texture3d.ImageTexture3D()
    texture.loadBackground([str(bad), str(tmp_path / 'missing.nrrd')])
    from vrml.x3d import loadsensor  # noqa: PLC0415 kept with its use
    assert texture.volumeData() is None
    assert loadsensor.load_state(texture) == loadsensor.FAILED


def test_a_dds_volume_is_read_too(tmp_path):
    header = struct.pack('<7I', 124, 0x801007, 1, 1, 0, 2, 1) + b'\0' * 44
    header += struct.pack('<2I4s5I', 32, 0x20000, b'\0\0\0\0', 8, 0xFF, 0, 0, 0)
    header += struct.pack('<4I', 0x1000, 0x200000, 0, 0) + b'\0' * 4
    path = tmp_path / 'volume.dds'
    path.write_bytes(b'DDS ' + header + bytes([3, 9]))
    texture = texture3d.ImageTexture3D()
    texture.loadBackground([str(path)])
    assert list(texture.volumeData().ravel()) == [3, 9]


def test_alpha_is_two_or_four_channels():
    assert texture3d.PixelTexture3D(image=[2, 1, 1, 1, 0xFF80]).hasAlpha()
    assert not texture3d.PixelTexture3D(image=[3, 1, 1, 1, 0xFF8000]).hasAlpha()


def test_the_volume_is_drawn_with_the_nodes_repeat_fields():
    texture = texture3d.PixelTexture3D(repeatR=True, image=[1, 1, 1, 1, 0])
    from OpenGLContext.scenegraph.sampler import sampler_of  # noqa: PLC0415 kept with its use
    found = sampler_of(texture)
    assert (found['wrap_s'], found['wrap_r']) == ('CLAMP_TO_EDGE', 'REPEAT')


def test_the_registered_nodes_are_these():
    from OpenGLContext.loaders.x3d import prototypes  # noqa: PLC0415 kept with its use
    found = prototypes()
    for name in ('ImageTexture3D', 'ComposedTexture3D', 'PixelTexture3D'):
        assert found[name] is getattr(texture3d, name)
    for name in ('TextureCoordinate3D', 'TextureCoordinate4D', 'TextureTransform3D'):
        assert found[name] is getattr(x3d, name)


def test_a_volume_uploads_as_a_3d_texture(gl_context):
    from OpenGL import GL  # noqa: PLC0415 GL
    from OpenGLContext.texture import VolumeTexture  # noqa: PLC0415 GL
    volume = np.arange(2 * 3 * 4, dtype=np.uint8).reshape(2, 3, 4, 1)
    texture = VolumeTexture(volume)
    texture.bind()
    found = [int(GL.glGetTexLevelParameteriv(GL.GL_TEXTURE_3D, 0, name)) for name in
             (GL.GL_TEXTURE_WIDTH, GL.GL_TEXTURE_HEIGHT, GL.GL_TEXTURE_DEPTH)]
    assert found == [4, 3, 2]
    assert texture.target == GL.GL_TEXTURE_3D and texture.components == 1


def volume_triangle(coordinate):
    from OpenGLContext.scenegraph.basenodes import IndexedTriangleSet  # noqa: PLC0415 kept with its use
    return IndexedTriangleSet(
        index=[0, 1, 2], coord=x3d.Coordinate(point=[(0, 0, 0), (1, 0, 0), (0, 1, 0)]),
        texCoord=x3d.MultiTextureCoordinate(texCoord=[
            x3d.TextureCoordinate(point=[(0, 0), (1, 0), (0, 1)]), coordinate]))


def test_a_set_with_3d_coordinates_carries_them_with_q_one():
    geometry = volume_triangle(x3d.TextureCoordinate3D(point=[(0, 0, 0.5), (1, 0, 0.5),
                                                               (0, 1, 1)]))
    mesh = geometry.mesh()
    assert mesh.texcoords3d.shape == (3, 4)
    assert tuple(mesh.texcoords3d[2]) == (0, 1, 1, 1)
    # The 3D set is not a 2D one: the first set stays TEXCOORD_0.
    assert mesh.texcoords is not None and mesh.texcoords1 is None


def test_a_set_with_4d_coordinates_carries_them_as_given():
    geometry = volume_triangle(x3d.TextureCoordinate4D(point=[(0, 0, 0, 2)] * 3))
    assert tuple(geometry.mesh().texcoords3d[0]) == (0, 0, 0, 2)


def test_the_3d_coordinates_are_read_at_their_own_location():
    from OpenGLContext.scenegraph import vertexsemantics  # noqa: PLC0415 kept with its use
    entry = vertexsemantics.BY_SEMANTIC['TEXCOORD_3D']
    assert (entry.location, entry.components, entry.attribute) == (15, 4, 'aTexCoord3D')
