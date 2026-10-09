"""X_ITE's ImageTextureAtlas: a 3D texture cut from the tiles of one 2D image.

The image is slicesOverX tiles across and slicesOverY down; the first
numberOfSlices of them, left to right along each row from the top row down,
are the slices from r=0 up, each with its top row at t=0, as X_ITE reads it.
"""
import io

import numpy as np
from PIL import Image

from OpenGLContext.scenegraph.texture3d import ImageTextureAtlas, atlas_volume


def tiled(across, down, size=4):
    """An RGB image of `across` x `down` tiles, tile k filled with grey k*10,
    each tile's top row red"""
    pixels = np.zeros((down * size, across * size, 3), np.uint8)
    for row in range(down):
        for column in range(across):
            index = row * across + column
            tile = pixels[row * size:(row + 1) * size, column * size:(column + 1) * size]
            tile[:] = index * 10
            tile[0] = (255, 0, 0)
    return Image.fromarray(pixels, 'RGB')


def test_the_tiles_are_the_slices_in_reading_order():
    volume = atlas_volume(tiled(3, 2), 3, 2, 5)
    assert volume.shape == (5, 4, 4, 3)
    assert [int(volume[index, 2, 2, 1]) for index in range(5)] == [0, 10, 20, 30, 40]


def test_a_slice_s_first_row_is_its_tile_s_top():
    volume = atlas_volume(tiled(2, 2), 2, 2, 4)
    assert tuple(volume[3, 0, 0]) == (255, 0, 0)
    assert tuple(volume[3, 3, 0]) == (30, 30, 30)


def test_more_slices_than_tiles_is_every_tile():
    assert atlas_volume(tiled(2, 1), 2, 1, 9).shape[0] == 2


def test_no_tiles_is_no_volume():
    assert atlas_volume(tiled(2, 1), 0, 1, 2) is None
    assert atlas_volume(tiled(2, 1), 2, 1, 0) is None


def test_the_node_reads_its_url(tmp_path):
    path = tmp_path / 'atlas.png'
    tiled(2, 2).save(path)
    atlas = ImageTextureAtlas(url=[str(path)], slicesOverX=2, slicesOverY=2, numberOfSlices=4)
    volume = atlas.loadBackground(atlas.url)
    assert volume is not None and volume.shape == (4, 4, 4, 3)
    assert (atlas.width, atlas.height, atlas.depth, atlas.colorDepth) == (4, 4, 4, 3)
    assert np.array_equal(atlas.volumeData(), volume)


def test_editing_the_slicing_cuts_the_image_again(tmp_path):
    path = tmp_path / 'atlas.png'
    buffer = io.BytesIO()
    tiled(2, 2).save(buffer, 'PNG')
    path.write_bytes(buffer.getvalue())
    atlas = ImageTextureAtlas(url=[str(path)], slicesOverX=2, slicesOverY=2, numberOfSlices=4)
    atlas.loadBackground(atlas.url)
    assert atlas.volumeData().shape[0] == 4
    atlas.numberOfSlices = 2
    assert atlas.volumeData().shape[0] == 2


def test_the_picture_is_kept_when_the_slicing_arrives_after_it(tmp_path):
    path = tmp_path / 'atlas.png'
    tiled(2, 2).save(path)
    atlas = ImageTextureAtlas()
    atlas.loadBackground([str(path)])
    assert atlas.volumeData() is None
    atlas.slicesOverX, atlas.slicesOverY, atlas.numberOfSlices = 2, 2, 4
    assert atlas.volumeData().shape == (4, 4, 4, 3)
