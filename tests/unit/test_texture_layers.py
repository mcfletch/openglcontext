"""The stage chain a MultiTexture, a cube map or a 3D texture is drawn as

``texturelayers.texture_layers`` reads an appearance and its geometry into
the layers the shaders combine: each layer's texture, what kind of sampler
reads it, where its coordinates come from, its transform, and the mode,
source and function that combine it with the colour so far.
"""
import os
import re

import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import texture3d, texturelayers
from OpenGLContext.scenegraph.basenodes import (
    Appearance, ImageTexture, IndexedTriangleSet, Material, MultiTexture, PhysicalMaterial,
    UnlitMaterial,
)
from OpenGLContext.scenegraph.cubemaptexture import ComposedCubeMapTexture
from OpenGLContext.testing.memo import check_memo_inputs
from OpenGLContext.scenegraph.texturelayers import (
    COORD_BOX, COORD_GENERATED, COORD_REFLECTION, COORD_SET, COORD_VOLUME, KIND_2D, KIND_3D,
    KIND_CUBE, MODES, SOURCES, FUNCTIONS,
)


def pixel(colour=0xFF0000):
    return x3d.PixelTexture(image=[1, 1, 3, colour])


def triangle(texCoord=None):
    return IndexedTriangleSet(index=[0, 1, 2], texCoord=texCoord,
                              coord=x3d.Coordinate(point=[(0, 0, 0), (1, 0, 0), (0, 1, 0)]))


@pytest.mark.parametrize('text, expected', [
    ('MODULATE', ('MODULATE', 'MODULATE')),
    ('ADD', ('ADD', 'ADD')),
    ('MODULATE,REPLACE', ('MODULATE', 'REPLACE')),
    ('BLEND_DIFFUSE_ALPHA, ADD_SIGNED', ('BLEND_DIFFUSE_ALPHA', 'ADD_SIGNED')),
    ('MODULATEALPHA_ADDCOLOR', ('MODULATE_ALPHA_ADD_COLOR', 'MODULATE_ALPHA_ADD_COLOR')),
    ('BLENDDIFFUSEALPHA', ('BLEND_DIFFUSE_ALPHA', 'BLEND_DIFFUSE_ALPHA')),
    ('DOTPRODUCT3', ('DOT_PRODUCT_3', 'DOT_PRODUCT_3')),
    ('modulate2x', ('MODULATE_2X', 'MODULATE_2X')),
])
def test_a_mode_names_the_colour_operation_and_the_alpha_one(text, expected):
    assert texturelayers.parse_mode(text) == tuple(MODES[name] for name in expected)


def test_a_mode_nobody_names_is_modulate_and_reported(caplog):
    assert texturelayers.parse_mode('SWIRL') == (MODES['MODULATE'], MODES['MODULATE'])
    assert 'SWIRL' in caplog.text


@pytest.mark.parametrize('text, expected', [
    ('', 0), ('DIFFUSE', SOURCES['DIFFUSE']), ('SPECULAR', SOURCES['SPECULAR']),
    ('FACTOR', SOURCES['FACTOR']),
])
def test_a_source_replaces_the_texture_as_the_first_argument(text, expected):
    assert texturelayers.parse_source(text) == expected


@pytest.mark.parametrize('text, expected', [
    ('', 0), ('COMPLEMENT', FUNCTIONS['COMPLEMENT']),
    ('ALPHAREPLICATE', FUNCTIONS['ALPHA_REPLICATE']),
    ('ALPHA_REPLICATE', FUNCTIONS['ALPHA_REPLICATE']),
])
def test_a_function_is_applied_to_the_first_argument(text, expected):
    assert texturelayers.parse_function(text) == expected


def test_the_shader_numbers_modes_sources_and_functions_as_this_module_does():
    from OpenGLContext.passes.shadersource import SHADER_DIR  # noqa: PLC0415 kept with its use
    with open(os.path.join(SHADER_DIR, '_layers_inc.glsl'), encoding='utf-8') as stream:
        source = stream.read()
    for prefix, table in (('LAYER_MODE_', MODES), ('LAYER_SOURCE_', SOURCES),
                          ('LAYER_FUNCTION_', FUNCTIONS)):
        found = {name: int(number) for name, number in
                 re.findall(r'#define %s([A-Z0-9_]+)\s+(\d+)' % prefix, source)}
        assert found == table
    kinds = {name: int(number) for name, number in
             re.findall(r'#define LAYER_KIND_([A-Z0-9_]+)\s+(\d+)', source)}
    assert kinds == {'2D': KIND_2D, 'CUBE': KIND_CUBE, '3D': KIND_3D}
    coordinates = {name: int(number) for name, number in
                   re.findall(r'#define LAYER_COORD_([A-Z0-9_]+)\s+(\d+)', source)}
    assert coordinates == {'SET': COORD_SET, 'GENERATED': COORD_GENERATED,
                           'VOLUME': COORD_VOLUME, 'BOX': COORD_BOX,
                           'REFLECTION': COORD_REFLECTION}


def test_an_ordinary_texture_has_no_layers():
    appearance = Appearance(material=Material(), texture=pixel())
    assert texturelayers.texture_layers(appearance, triangle()) is None
    assert texturelayers.texture_layers(None, triangle()) is None


def test_a_multitexture_is_a_layer_per_texture_with_its_mode_source_and_function():
    multi = MultiTexture(texture=[pixel(), pixel(), pixel()],
                         mode=['MODULATE', 'ADD,REPLACE'], source=['', 'DIFFUSE'],
                         function=['COMPLEMENT'], color=(0.25, 0.5, 0.75), alpha=0.5)
    table = texturelayers.texture_layers(Appearance(material=Material(), texture=multi),
                                         triangle())
    assert [layer.texture for layer in table.layers] == list(multi.texture)
    assert [layer.kind for layer in table.layers] == [KIND_2D] * 3
    assert [(layer.mode, layer.alpha_mode) for layer in table.layers] == [
        (MODES['MODULATE'], MODES['MODULATE']), (MODES['ADD'], MODES['REPLACE']),
        (MODES['MODULATE'], MODES['MODULATE'])]
    assert [layer.source for layer in table.layers] == [0, SOURCES['DIFFUSE'], 0]
    assert [layer.function for layer in table.layers] == [FUNCTIONS['COMPLEMENT'], 0, 0]
    assert table.factor == pytest.approx((0.25, 0.5, 0.75, 0.5))


def test_a_cube_map_or_a_volume_by_itself_is_one_modulating_layer():
    cube = ComposedCubeMapTexture()
    table = texturelayers.texture_layers(Appearance(material=Material(), texture=cube),
                                         triangle())
    (layer,) = table.layers
    assert (layer.kind, layer.coordinate, layer.mode) == (
        KIND_CUBE, COORD_REFLECTION, MODES['MODULATE'])
    volume = texture3d.PixelTexture3D(image=[1, 1, 1, 1, 0])
    (layer,) = texturelayers.texture_layers(Appearance(texture=volume), triangle()).layers
    assert (layer.kind, layer.coordinate) == (KIND_3D, COORD_BOX)


def test_layers_come_from_the_base_map_of_every_material():
    multi = MultiTexture(texture=[pixel()])
    for material in (Material(), UnlitMaterial(), PhysicalMaterial(), None):
        table = texturelayers.texture_layers(Appearance(material=material, texture=multi),
                                             triangle())
        assert table is not None and len(table.layers) == 1


def test_a_layer_takes_the_coordinate_set_at_its_position_or_the_last():
    coordinates = x3d.MultiTextureCoordinate(texCoord=[
        x3d.TextureCoordinate(point=[(0, 0)] * 3), x3d.TextureCoordinate(point=[(1, 1)] * 3)])
    multi = MultiTexture(texture=[pixel(), pixel(), pixel()])
    table = texturelayers.texture_layers(Appearance(texture=multi), triangle(coordinates))
    assert [(layer.coordinate, layer.set) for layer in table.layers] == [
        (COORD_SET, 0), (COORD_SET, 1), (COORD_SET, 1)]


def test_a_coordinate_set_past_the_second_is_read_as_the_first_and_reported(caplog):
    coordinates = x3d.MultiTextureCoordinate(texCoord=[
        x3d.TextureCoordinate(point=[(0, 0)] * 3) for _ in range(3)])
    multi = MultiTexture(texture=[pixel(), pixel(), pixel()])
    table = texturelayers.texture_layers(Appearance(texture=multi), triangle(coordinates))
    assert table.layers[2].set == 0
    assert 'coordinate set 2' in caplog.text


def test_a_generator_makes_its_layers_coordinates_in_its_mode():
    generator = x3d.TextureCoordinateGenerator(mode='NOISE', parameter=[2, 2, 2])
    coordinates = x3d.MultiTextureCoordinate(texCoord=[
        x3d.TextureCoordinate(point=[(0, 0)] * 3), generator])
    multi = MultiTexture(texture=[pixel(), pixel()])
    table = texturelayers.texture_layers(Appearance(texture=multi), triangle(coordinates))
    layer = table.layers[1]
    from OpenGLContext.scenegraph import texgen  # noqa: PLC0415 kept with its use
    assert (layer.coordinate, layer.generator) == (COORD_GENERATED, texgen.MODES['NOISE'])
    assert layer.parameters[:3] == (2.0, 2.0, 2.0)


def test_a_volume_reads_a_3d_coordinate_set():
    coordinates = x3d.MultiTextureCoordinate(texCoord=[
        x3d.TextureCoordinate(point=[(0, 0)] * 3),
        x3d.TextureCoordinate3D(point=[(0, 0, 0)] * 3)])
    volume = texture3d.PixelTexture3D(image=[1, 1, 1, 1, 0])
    multi = MultiTexture(texture=[pixel(), volume])
    table = texturelayers.texture_layers(Appearance(texture=multi), triangle(coordinates))
    assert table.layers[1].coordinate == COORD_VOLUME
    assert table.layers[0].coordinate == COORD_SET


def test_a_cube_map_reads_the_reflection_whatever_its_coordinates():
    coordinates = x3d.MultiTextureCoordinate(texCoord=[
        x3d.TextureCoordinateGenerator(mode='SPHERE')])
    multi = MultiTexture(texture=[ComposedCubeMapTexture()])
    table = texturelayers.texture_layers(Appearance(texture=multi), triangle(coordinates))
    assert table.layers[0].coordinate == COORD_REFLECTION


def test_a_layer_takes_the_transform_at_its_position_or_the_last():
    transforms = x3d.MultiTextureTransform(textureTransform=[
        x3d.TextureTransform(translation=(0.5, 0)),
        x3d.TextureTransform(scale=(2, 2))])
    multi = MultiTexture(texture=[pixel(), pixel(), pixel()])
    table = texturelayers.texture_layers(
        Appearance(texture=multi, textureTransform=transforms), triangle())
    first, second, third = (layer.transform for layer in table.layers)
    assert first @ (0, 0, 0, 1) == pytest.approx((0.5, 0, 0))
    assert second @ (1, 1, 0, 1) == pytest.approx((2, 2, 0))
    assert third @ (1, 1, 0, 1) == pytest.approx((2, 2, 0))


def test_a_single_transform_applies_to_every_layer():
    multi = MultiTexture(texture=[pixel(), pixel()])
    table = texturelayers.texture_layers(
        Appearance(texture=multi, textureTransform=x3d.TextureTransform(rotation=np.pi / 2)),
        triangle())
    for layer in table.layers:
        assert layer.transform @ (1, 0, 0, 1) == pytest.approx((0, 1, 0), abs=1e-6)


def test_a_transform_3d_composes_as_a_2d_transform_does():
    parameters = dict(translation=(0.25, 0.5), scale=(2, 3), center=(0.5, 0.5), rotation=0.75)
    flat = texturelayers.transform_matrix(x3d.TextureTransform(**parameters))
    deep = texturelayers.transform_matrix(x3d.TextureTransform3D(
        translation=(0.25, 0.5, 0), scale=(2, 3, 1), center=(0.5, 0.5, 0),
        rotation=(0, 0, 1, 0.75)))
    assert deep == pytest.approx(flat, abs=1e-6)


def test_a_transform_3d_scales_and_moves_r_as_well():
    deep = texturelayers.transform_matrix(x3d.TextureTransform3D(
        translation=(0, 0, 0.5), scale=(1, 1, 2)))
    assert deep @ (0, 0, 1, 1) == pytest.approx((0, 0, 3))


def test_a_transform_matrix_3d_is_its_matrix():
    rows = np.arange(16, dtype=float).reshape(4, 4)
    transform = x3d.TextureTransformMatrix3D(matrix=rows.ravel())
    assert texturelayers.transform_matrix(transform) == pytest.approx(rows[:3])


def test_a_multitexture_past_the_layers_the_shader_reads_is_cut_and_reported(caplog):
    multi = MultiTexture(texture=[pixel()] * (texturelayers.MAX_LAYERS + 2))
    table = texturelayers.texture_layers(Appearance(texture=multi), triangle())
    assert len(table.layers) == texturelayers.MAX_LAYERS
    assert 'layers' in caplog.text


def test_a_multitexture_inside_a_multitexture_is_left_out(caplog):
    inner = MultiTexture(texture=[pixel()])
    table = texturelayers.texture_layers(
        Appearance(texture=MultiTexture(texture=[inner, pixel()])), triangle())
    assert len(table.layers) == 1
    assert 'MultiTexture' in caplog.text


def test_the_layers_follow_every_field_they_are_read_from():
    first = pixel()
    multi = MultiTexture(texture=[first], mode=['MODULATE'])
    transform = x3d.TextureTransform()
    appearance = Appearance(material=Material(), texture=multi, textureTransform=transform)
    coordinate = x3d.TextureCoordinateGenerator(mode='COORD')
    geometry = triangle(x3d.MultiTextureCoordinate(texCoord=[coordinate]))

    def summary(table):
        return None if table is None else table.key

    check_memo_inputs(
        lambda: summary(texturelayers.texture_layers(appearance, geometry)), [
            ('MultiTexture.mode', lambda: setattr(multi, 'mode', ['ADD'])),
            ('MultiTexture.source', lambda: setattr(multi, 'source', ['FACTOR'])),
            ('MultiTexture.function', lambda: setattr(multi, 'function', ['COMPLEMENT'])),
            ('MultiTexture.color', lambda: setattr(multi, 'color', (0.5, 0.5, 0.5))),
            ('MultiTexture.alpha', lambda: setattr(multi, 'alpha', 0.5)),
            ('MultiTexture.texture', lambda: setattr(multi, 'texture', [first, pixel()])),
            ('TextureTransform.scale', lambda: setattr(transform, 'scale', (3, 3))),
            ('Appearance.textureTransform',
             lambda: setattr(appearance, 'textureTransform', x3d.TextureTransform(
                 translation=(1, 0)))),
            ('generator.mode', lambda: setattr(coordinate, 'mode', 'NOISE')),
            ('geometry.texCoord', lambda: setattr(geometry, 'texCoord', None)),
            ('Appearance.texture', lambda: setattr(appearance, 'texture', ComposedCubeMapTexture())),
        ],
        fresh=lambda: summary(texturelayers.compute_layers(appearance, geometry)))
