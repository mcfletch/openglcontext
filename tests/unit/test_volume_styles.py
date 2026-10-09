"""X3D's volume render styles as a plan for the ray march: no GL

``volumestyles.plan`` turns a volume data node and its render styles into the
GLSL the march compiles, keyed by a signature, and the values and textures it
is given each frame. The colour tables (the cartoon palette, transfer
functions, isosurface values) are worked out here from the specification's
rules (ISO/IEC 19775-1, 41.4).
"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import texture3d, volumestyles


def grey_volume(size=4, channels=1, value=128):
    count = size * size * size
    pixel = sum(value << (8 * index) for index in range(channels))
    return texture3d.PixelTexture3D(image=[channels, size, size, size] + [pixel] * count)


def data(style=None, **named):
    node = x3d.VolumeData(voxels=grey_volume(), **named)
    if style is not None:
        node.renderStyle = style
    return node


def kinds(found):
    return [step.kind for step in found.steps]


# -- the cartoon palette (41.4.3) --------------------------------------------

def test_the_cartoon_palette_of_the_default_style_is_the_specifications_example():
    palette = volumestyles.cartoon_palette((1, 1, 1, 1), (0, 0, 0, 1), 4)
    assert np.allclose(palette, [(1, 1, 1, 1), (0.625, 0.625, 0.625, 1),
                                 (0.375, 0.375, 0.375, 1), (0, 0, 0, 1)])


def test_one_cartoon_step_is_the_orthogonal_colour_alone():
    palette = volumestyles.cartoon_palette((0.2, 0.4, 0.6, 1), (0, 0, 0, 1), 1)
    assert np.allclose(palette, [(0.2, 0.4, 0.6, 1)])


def test_cartoon_colours_between_the_ends_are_interpolated_in_hsv():
    red, blue = (1.0, 0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 0.0)
    palette = volumestyles.cartoon_palette(red, blue, 3)
    # Hue half way from red (0) to blue (2/3) the short way round is 5/6,
    # magenta; alpha is linear.
    assert np.allclose(palette[1], (1.0, 0.0, 1.0, 0.5))


def test_cartoon_steps_out_of_range_are_held_to_one_and_sixty_four():
    assert len(volumestyles.cartoon_palette((1, 1, 1, 1), (0, 0, 0, 1), 0)) == 1
    assert len(volumestyles.cartoon_palette((1, 1, 1, 1), (0, 0, 0, 1), 99)) == 64


# -- transfer functions (Tables 41.5, 41.6) ------------------------------------

@pytest.mark.parametrize('channels, pixel, expected', [
    (1, [90], (90, 90, 90, 255)),
    (2, [90, 30], (90, 90, 90, 30)),
    (3, [10, 20, 30], (10, 20, 30, 255)),
    (4, [10, 20, 30, 40], (10, 20, 30, 40)),
])
def test_a_transfer_table_is_rgba_by_table_41_6(channels, pixel, expected):
    pixels = np.array(pixel, np.uint8).reshape(1, 1, channels)
    assert tuple(volumestyles.rgba_table(pixels)[0, 0]) == expected


def test_the_transfer_table_of_a_two_dimensional_texture_is_its_pixels():
    texture = x3d.PixelTexture(image=[2, 1, 2, 0x0000, 0xFF80])
    table = volumestyles.transfer_table(texture)
    assert table.shape == (1, 2, 4)
    assert tuple(table[0, 1]) == (255, 255, 255, 128)


def test_the_transfer_table_of_a_three_dimensional_texture_is_its_volume():
    table = volumestyles.transfer_table(grey_volume(size=2, channels=3, value=7))
    assert table.shape == (2, 2, 2, 4)
    assert tuple(table[1, 1, 1]) == (7, 7, 7, 255)


def test_a_texture_with_no_pixels_has_no_transfer_table():
    assert volumestyles.transfer_table(x3d.PixelTexture()) is None
    assert volumestyles.transfer_table(None) is None


# -- isosurface values (41.4.6) ------------------------------------------------

def test_one_surface_value_with_no_step_is_one_surface_drawn_in_the_first_style():
    assert volumestyles.isosurfaces([0.25], 0.0, 2) == [(0.25, 0)]


def test_a_step_adds_every_multiple_of_it_from_the_surface_value():
    found = volumestyles.isosurfaces([0.25], 0.1, 9)
    values = [round(value, 6) for value, _style in found]
    assert values == [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]


def test_stepped_surfaces_take_styles_from_the_smallest_after_the_first():
    found = dict((round(value, 6), style)
                 for value, style in volumestyles.isosurfaces([0.25], 0.1, 4))
    assert found[0.25] == 0
    assert (found[0.05], found[0.15], found[0.35]) == (1, 2, 3)
    assert found[0.95] == 3          # the last style for every surface past the styles


def test_a_negative_step_steps_the_same_values():
    assert (volumestyles.isosurfaces([0.25], -0.1, 1)
            == volumestyles.isosurfaces([0.25], 0.1, 1))


def test_several_surface_values_ignore_the_step_and_take_styles_by_index():
    assert volumestyles.isosurfaces([0.2, 0.6, 0.4], 0.1, 2) == [
        (0.2, 0), (0.4, 1), (0.6, 1)]


def test_no_surface_value_is_no_surface():
    assert volumestyles.isosurfaces([], 0.1, 1) == []


def test_steps_finer_than_the_limit_keep_the_surfaces_nearest_the_value():
    found = volumestyles.isosurfaces([0.5], 0.001, 1)
    assert len(found) == volumestyles.MAX_ISOSURFACES
    values = [value for value, _style in found]
    assert min(values) > 0.45 and max(values) < 0.55
    assert (0.5, 0) in found


# -- plans -----------------------------------------------------------------------

def test_a_volume_with_no_style_is_drawn_by_the_default_opacity_map():
    found = volumestyles.plan(data())
    assert found.mode == 'composite'
    assert kinds(found) == ['default']
    assert found.channels == 1


def test_a_disabled_style_is_drawn_as_though_it_were_not_there():
    found = volumestyles.plan(data(x3d.ToneMappedVolumeStyle(enabled=False)))
    assert kinds(found) == ['default']


def test_a_composed_style_applies_its_enabled_styles_in_order():
    composed = x3d.ComposedVolumeStyle(renderStyle=[
        x3d.OpacityMapVolumeStyle(), x3d.EdgeEnhancementVolumeStyle(enabled=False),
        x3d.SilhouetteEnhancementVolumeStyle()])
    found = volumestyles.plan(data(composed))
    assert kinds(found) == ['composed', 'opacity', 'silhouette']
    assert found.steps[0].children == (1, 2)


def test_every_style_has_glsl_that_names_its_function():
    styles = [
        x3d.OpacityMapVolumeStyle(), x3d.BoundaryEnhancementVolumeStyle(),
        x3d.CartoonVolumeStyle(), x3d.EdgeEnhancementVolumeStyle(),
        x3d.ShadedVolumeStyle(lighting=True, material=x3d.Material()),
        x3d.SilhouetteEnhancementVolumeStyle(), x3d.ToneMappedVolumeStyle(),
        x3d.BlendedVolumeStyle(voxels=grey_volume()),
    ]
    found = volumestyles.plan(data(x3d.ComposedVolumeStyle(renderStyle=styles)))
    source = found.source()
    for index in range(len(found.steps)):
        assert 'vec4 style%d(vec4 c, VSample s)' % (index,) in source
    assert 'vec4 volumeStyle(VSample s)' in source


def test_the_signature_follows_what_the_glsl_is_made_from():
    edge = x3d.EdgeEnhancementVolumeStyle()
    node = data(edge)
    first = volumestyles.plan(node).signature
    edge.gradientThreshold = 0.9                 # a value: the same program
    assert volumestyles.plan(node).signature == first
    edge.surfaceNormals = grey_volume(channels=3)
    assert volumestyles.plan(node).signature != first
    node.renderStyle = x3d.ComposedVolumeStyle(renderStyle=[edge])
    assert volumestyles.plan(node).signature != first


def test_the_signature_follows_the_number_of_channels_the_data_has():
    node = data(x3d.OpacityMapVolumeStyle(transferFunction=x3d.PixelTexture(
        image=[1, 1, 2, 0xFF00])))
    first = volumestyles.plan(node).signature
    node.voxels = grey_volume(channels=2)
    assert volumestyles.plan(node).signature != first


def test_a_style_values_come_from_its_fields():
    style = x3d.BoundaryEnhancementVolumeStyle(boundaryOpacity=0.7, opacityFactor=3.0,
                                               retainedOpacity=0.1)
    found = volumestyles.plan(data(style))
    values = found.values()
    assert values['s0_retained'] == pytest.approx(0.1)
    assert values['s0_boundary'] == pytest.approx(0.7)
    assert values['s0_exponent'] == pytest.approx(3.0)


def test_the_cartoon_style_is_given_its_palette():
    found = volumestyles.plan(data(x3d.CartoonVolumeStyle()))
    values = found.values()
    assert values['s0_steps'] == 4
    assert np.allclose(values['s0_palette'][:4, 0], [1, 0.625, 0.375, 0])


def test_a_transfer_function_is_a_table_texture():
    table = x3d.PixelTexture(image=[2, 1, 1, 0x00, 0xFF])
    found = volumestyles.plan(data(x3d.OpacityMapVolumeStyle(transferFunction=table)))
    assert [(slot.name, slot.kind) for slot in found.textures] == [('s0_table', 'table2d')]
    assert found.textures[0].node is table


def test_a_surface_normal_texture_of_fewer_than_three_channels_is_ignored():
    style = x3d.EdgeEnhancementVolumeStyle(surfaceNormals=grey_volume(channels=1))
    found = volumestyles.plan(data(style))
    assert not found.textures


def test_the_shaded_style_reads_its_material():
    material = x3d.Material(diffuseColor=(1, 0.5, 0), transparency=0.25, shininess=0.5)
    found = volumestyles.plan(data(x3d.ShadedVolumeStyle(lighting=True, material=material)))
    values = found.values()
    assert np.allclose(values['s0_diffuse'], (1, 0.5, 0))
    assert values['s0_opacity'] == pytest.approx(0.75)
    assert values['s0_shininess'] == pytest.approx(0.5)
    assert found.lights


def test_a_style_that_needs_no_lights_does_not_ask_for_them():
    assert not volumestyles.plan(data(x3d.EdgeEnhancementVolumeStyle())).lights


def test_the_blended_style_reads_a_second_volume():
    second = grey_volume(channels=3)
    style = x3d.BlendedVolumeStyle(voxels=second, weightFunction1='ALPHA2',
                                   weightFunction2='TABLE')
    found = volumestyles.plan(data(style))
    assert [(slot.name, slot.kind) for slot in found.textures] == [('s0_voxels', 'volume')]
    assert found.textures[0].node is second
    source = found.source()
    assert 'blend.a' in source            # ALPHA2 is the second volume's opacity
    assert 's0_weightTable2' not in source  # TABLE with no table is Ov


def test_a_blended_style_with_no_second_volume_is_the_volume_it_blends_into():
    found = volumestyles.plan(data(x3d.BlendedVolumeStyle()))
    assert kinds(found) == ['default']


def test_a_projection_style_is_its_own_march():
    found = volumestyles.plan(data(x3d.ProjectionVolumeStyle(type='MIN',
                                                             intensityThreshold=0.3)))
    assert found.mode == 'projection'
    assert found.values()['projectionType'] == volumestyles.PROJECTIONS['MIN']
    assert found.values()['projectionThreshold'] == pytest.approx(0.3)


def test_a_volume_whose_data_has_not_loaded_has_no_plan():
    assert volumestyles.plan(x3d.VolumeData()) is None
    assert volumestyles.plan(x3d.VolumeData(voxels=texture3d.ImageTexture3D())) is None


def test_segments_choose_their_styles_by_identifier():
    node = x3d.SegmentedVolumeData(
        voxels=grey_volume(), segmentIdentifiers=grey_volume(value=1),
        renderStyle=[x3d.OpacityMapVolumeStyle(), x3d.ToneMappedVolumeStyle()],
        segmentEnabled=[True, False])
    found = volumestyles.plan(node)
    assert found.segmented
    assert [step.kind for step in found.steps] == ['opacity', 'tone']
    assert found.segments == (0, 1)
    off = found.values()['segmentsOff']
    assert off[0] == 0b10                   # segment 1 is not drawn
    assert [slot.name for slot in found.textures] == ['segments']


def test_segment_identifiers_of_another_size_than_the_voxels_are_ignored():
    node = x3d.SegmentedVolumeData(
        voxels=grey_volume(), segmentIdentifiers=grey_volume(size=2),
        renderStyle=[x3d.ToneMappedVolumeStyle()])
    found = volumestyles.plan(node)
    assert not found.segmented
    assert kinds(found) == ['tone']


def test_a_segmented_volume_with_no_styles_draws_every_segment_by_default():
    node = x3d.SegmentedVolumeData(voxels=grey_volume(), segmentIdentifiers=grey_volume())
    assert kinds(volumestyles.plan(node)) == ['default']


def test_an_isosurface_volume_lists_its_surfaces_and_their_styles():
    node = x3d.IsoSurfaceVolumeData(
        voxels=grey_volume(), surfaceValues=[0.3], contourStepSize=0.2,
        renderStyle=[x3d.OpacityMapVolumeStyle(), x3d.ToneMappedVolumeStyle()],
        surfaceTolerance=0.05)
    found = volumestyles.plan(node)
    assert found.mode == 'isosurface'
    values = found.values()
    assert values['isoCount'] == 5
    assert np.allclose(values['isoValues'][:5], [0.1, 0.3, 0.5, 0.7, 0.9])
    assert list(values['isoStyles'][:5]) == [1, 0, 1, 1, 1]
    assert values['isoTolerance'] == pytest.approx(0.05)


def test_an_isosurface_with_no_style_is_drawn_in_its_own_colour():
    node = x3d.IsoSurfaceVolumeData(voxels=grey_volume(), surfaceValues=[0.3])
    found = volumestyles.plan(node)
    assert kinds(found) == ['surface']


def test_a_clear_voxel_stays_clear_unless_a_style_gives_opacity_of_its_own():
    assert volumestyles.plan(data(x3d.ToneMappedVolumeStyle())).clearStaysClear
    table = x3d.PixelTexture(image=[1, 1, 2, 0xFFFF])
    assert not volumestyles.plan(data(x3d.OpacityMapVolumeStyle(
        transferFunction=table))).clearStaysClear
    assert not volumestyles.plan(data(x3d.BlendedVolumeStyle(
        voxels=grey_volume()))).clearStaysClear
    assert not volumestyles.plan(data(x3d.ProjectionVolumeStyle())).clearStaysClear
