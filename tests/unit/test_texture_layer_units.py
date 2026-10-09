"""How a program with few texture units reads a chain: what fits is drawn

``pack_layers`` gives each layer a unit from the program's
``LayerUnits``; a layer with none left, or whose texture has no picture yet,
has no kind, and the shader leaves it out of the chain.
"""
from types import SimpleNamespace

import numpy as np
from vrml.x3d import nodes as x3d

from OpenGLContext.passes.texturelayerpass import LayerUnits, pack_layers
from OpenGLContext.scenegraph import texturelayers
from OpenGLContext.scenegraph.cubemaptexture import ComposedCubeMapTexture
from OpenGLContext.scenegraph.texturelayers import KIND_2D, KIND_CUBE, Layer, LayerTable

GL_TEXTURE_2D, GL_TEXTURE_CUBE_MAP = 0x0DE1, 0x8513


class Drawn:
    """A texture node whose picture the context holds"""

    def __init__(self, name, target=GL_TEXTURE_2D, kind=KIND_2D):
        self.held = SimpleNamespace(texture=name, target=target)
        self.kind = kind

    def cached(self, mode):
        return self.held


def table(*textures, source=0):
    return LayerTable(tuple(
        Layer(texture, texture.kind, texturelayers.COORD_SET, 0, 0, (0.0,) * 8,
              np.eye(4, dtype=np.float32)[:3], 1, 1, source, 0)
        for texture in textures), (1.0, 1.0, 1.0, 1.0))


def test_each_2d_layer_takes_the_next_slot():
    packed = pack_layers(table(Drawn(7), Drawn(8)), LayerUnits((1, 16, 17)), None)
    assert packed.binds == ((1, GL_TEXTURE_2D, 7), (16, GL_TEXTURE_2D, 8))
    assert [int(row[3]) for row in packed.info[:2]] == [0, 1]
    assert [int(row[0]) & 3 for row in packed.info[:2]] == [KIND_2D, KIND_2D]


def test_a_2d_layer_past_the_slots_is_left_out_and_reported(caplog):
    packed = pack_layers(table(Drawn(7), Drawn(8)), LayerUnits((1,)), None)
    assert packed.binds == ((1, GL_TEXTURE_2D, 7),)
    assert int(packed.info[1][0]) & 3 == 0
    assert 'more 2D layers' in caplog.text


def test_a_cube_map_with_no_unit_is_left_out_and_reported(caplog):
    cube = Drawn(9, GL_TEXTURE_CUBE_MAP, KIND_CUBE)
    packed = pack_layers(table(cube), LayerUnits((1,)), None)
    assert packed.binds == () and int(packed.info[0][0]) & 3 == 0
    assert 'cube map layer is left out' in caplog.text
    packed = pack_layers(table(cube), LayerUnits((1,), cube=32, volume=33), None)
    assert packed.binds == ((32, GL_TEXTURE_CUBE_MAP, 9),)


def test_a_layer_with_no_picture_yet_is_left_out():
    unloaded = Drawn(0)
    unloaded.held = None
    packed = pack_layers(table(unloaded), LayerUnits((1,)), None)
    assert packed.binds == () and int(packed.info[0][0]) & 3 == 0


def test_a_layer_reading_a_source_needs_no_texture():
    unloaded = Drawn(0)
    unloaded.held = None
    packed = pack_layers(table(unloaded, source=texturelayers.SOURCES['FACTOR']),
                         LayerUnits((1,)), None)
    assert packed.binds == () and int(packed.info[0][0]) & 3 == KIND_2D


def test_a_real_cube_node_reads_through_its_cached_cube():
    assert texturelayers.layer_kind(ComposedCubeMapTexture()) == KIND_CUBE
    assert texturelayers.layer_kind(x3d.PixelTexture()) == KIND_2D
