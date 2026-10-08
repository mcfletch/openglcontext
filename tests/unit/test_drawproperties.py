"""Tests for drawproperties: X3D's LineProperties, PointProperties and
FillProperties as the values a draw uses

Widths and sizes are in pixels; a line's dash pattern is in pixels too,
scaled with its width.
"""
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import drawproperties


def test_no_properties_is_a_one_pixel_solid_line():
    style = drawproperties.line_style(None)
    assert style.width == 1.0 and style.pattern == () and style.plain


def test_the_scale_factor_widens_the_line():
    style = drawproperties.line_style(x3d.LineProperties(linewidthScaleFactor=3))
    assert style.width == 3.0 and not style.plain


@pytest.mark.parametrize('scale', [0, -2])
def test_a_scale_at_or_below_zero_is_the_nominal_width(scale):
    assert drawproperties.line_style(x3d.LineProperties(linewidthScaleFactor=scale)).width == 1.0


def test_properties_not_applied_are_the_default():
    style = drawproperties.line_style(x3d.LineProperties(applied=False, linetype=2,
                                                         linewidthScaleFactor=4))
    assert style.plain


@pytest.mark.parametrize('linetype, dashes', [(2, 2), (3, 2), (4, 4), (5, 6)])
def test_the_five_required_linetypes_have_their_patterns(linetype, dashes):
    style = drawproperties.line_style(x3d.LineProperties(linetype=linetype))
    assert len(style.pattern) == dashes
    assert all(length > 0 for length in style.pattern)


def test_a_pattern_scales_with_the_width():
    thin = drawproperties.line_style(x3d.LineProperties(linetype=2))
    wide = drawproperties.line_style(x3d.LineProperties(linetype=2, linewidthScaleFactor=3))
    assert wide.pattern == tuple(3 * length for length in thin.pattern)


def test_a_linetype_past_the_required_five_is_solid_and_reported(caplog):
    style = drawproperties.line_style(x3d.LineProperties(linetype=9))
    assert style.pattern == ()
    assert 'linetype 9' in caplog.text


def test_point_size_follows_x3ds_attenuation():
    points = x3d.PointProperties(pointSizeScaleFactor=8, pointSizeMinValue=1,
                                 pointSizeMaxValue=10, attenuation=(1, 0.5, 0))
    size = drawproperties.point_size(points)
    assert size.scale == 8 and size.minimum == 1 and size.maximum == 10
    assert size.at(0) == 8 and size.at(2) == 4 and size.at(1000) == 1


def test_no_point_properties_is_the_nominal_size():
    size = drawproperties.point_size(None)
    assert (size.scale, size.minimum, size.maximum) == (1.0, 1.0, 1.0)
    assert size.at(5) == 1.0


def test_an_attenuation_reaching_zero_is_the_largest_size():
    size = drawproperties.point_size(x3d.PointProperties(
        attenuation=(0, 0, 0), pointSizeScaleFactor=2, pointSizeMaxValue=6))
    assert size.at(0) == 6


@pytest.mark.parametrize('style, code', [(1, 1), (6, 6)])
def test_a_hatch_style_is_its_number(style, code):
    fill = drawproperties.fill_style(x3d.FillProperties(hatchStyle=style, hatchColor=(1, 0, 0)))
    assert fill.hatch == code and fill.color == (1.0, 0.0, 0.0) and fill.filled


def test_no_fill_properties_is_filled_without_hatching():
    fill = drawproperties.fill_style(None)
    assert fill.filled and fill.hatch == 0 and fill.plain


def test_unhatched_is_no_hatch():
    assert drawproperties.fill_style(x3d.FillProperties(hatched=False)).hatch == 0


def test_neither_filled_nor_hatched_draws_nothing():
    assert drawproperties.fill_style(x3d.FillProperties(filled=False, hatched=False)).invisible


def test_a_hatch_style_past_six_is_style_one_and_reported(caplog):
    fill = drawproperties.fill_style(x3d.FillProperties(hatchStyle=12))
    assert fill.hatch == 1
    assert 'hatchStyle 12' in caplog.text


def test_a_solid_line_stipples_every_bit():
    assert drawproperties.stipple(drawproperties.line_style(None)) == (1, 0xFFFF)


def test_a_dashed_line_stipples_its_dash_then_its_gap():
    factor, bits = drawproperties.stipple(drawproperties.line_style(
        x3d.LineProperties(linetype=2)))
    assert factor == 1
    assert bits == 0x07FF  # two thirds drawn, a third gap


def test_a_long_pattern_stretches_each_bit():
    factor, bits = drawproperties.stipple(drawproperties.line_style(
        x3d.LineProperties(linetype=2, linewidthScaleFactor=4)))
    assert factor == 3 and bits == 0x07FF


def test_a_horizontal_hatch_stipples_every_eighth_row():
    mask = drawproperties.hatch_stipple(drawproperties.fill_style(
        x3d.FillProperties(hatchStyle=1)))
    rows = [mask[row * 4:row * 4 + 4] for row in range(32)]
    assert [row == b'\xff' * 4 for row in rows] == [row % 8 == 0 for row in range(32)]
    assert all(row in (b'\xff' * 4, b'\x00' * 4) for row in rows)


def test_a_vertical_hatch_stipples_every_eighth_column():
    mask = drawproperties.hatch_stipple(drawproperties.fill_style(
        x3d.FillProperties(hatchStyle=2)))
    assert set(mask) == {0x80}
