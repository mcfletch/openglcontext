"""Tests for pillowtext, which draws a line of text with Pillow.

``size`` is the face's em in the node's units. A line's image is its ink,
anti-aliased, at the pixels per unit asked, and its edges are given about
the line's origin on the baseline.
"""
import numpy as np
import pytest
from vrml.vrml97 import basenodes

from OpenGLContext.scenegraph.text import pillowtext


@pytest.fixture(scope='module')
def regular():
    return pillowtext.face_file(basenodes.FontStyle(family=['SERIF']))


@pytest.mark.parametrize('style, suffix', [
    ('PLAIN', 'Regular'), ('BOLD', 'Bold'), ('ITALIC', 'Italic'), ('BOLDITALIC', 'BoldItalic'),
])
def test_a_style_chooses_the_face(style, suffix):
    found = pillowtext.face_file(basenodes.FontStyle(family=['Open Sans'], style=style))
    assert found.endswith('OpenSans-%s.ttf' % suffix)


def test_the_advance_is_kerned(regular):
    """A pair the face kerns is narrower than its letters set apart"""
    apart = (pillowtext.advance(regular, 'A', 1.0) + pillowtext.advance(regular, 'V', 1.0))
    assert pillowtext.advance(regular, 'AV', 1.0) < apart - 0.01


def test_the_advance_scales_with_the_size(regular):
    assert pillowtext.advance(regular, 'Hello', 2.0) == pytest.approx(
        2 * pillowtext.advance(regular, 'Hello', 1.0), rel=0.01)


def test_a_line_is_its_ink_about_the_baseline(regular):
    line = pillowtext.draw_line(regular, 'Hxg', size=1.0, pixels_per_unit=64)
    assert line.left <= 0.05 and line.right >= pillowtext.advance(regular, 'Hx', 1.0)
    # the capital rises about 0.7 em above the baseline; the g's tail falls below it
    assert 0.6 < line.top < 1.0
    assert -0.4 < line.bottom < -0.1
    height, width = line.image.size[1], line.image.size[0]
    assert width == pytest.approx((line.right - line.left) * 64, abs=2)
    assert height == pytest.approx((line.top - line.bottom) * 64, abs=2)


def test_the_image_is_white_with_the_coverage_in_alpha(regular):
    line = pillowtext.draw_line(regular, 'H', size=1.0, pixels_per_unit=48)
    pixels = np.asarray(line.image)
    assert line.image.mode == 'LA'
    assert (pixels[:, :, 0] == 255).all()
    alpha = pixels[:, :, 1]
    assert alpha.max() == 255 and alpha.min() == 0
    assert ((alpha > 0) & (alpha < 255)).any(), 'edges are anti-aliased'


def test_more_pixels_per_unit_is_a_larger_image_of_the_same_extent(regular):
    small = pillowtext.draw_line(regular, 'Text', size=1.0, pixels_per_unit=32)
    large = pillowtext.draw_line(regular, 'Text', size=1.0, pixels_per_unit=128)
    assert large.image.size[0] > 3.5 * small.image.size[0]
    assert large.right - large.left == pytest.approx(small.right - small.left, rel=0.08)


def test_an_empty_line_has_no_image(regular):
    line = pillowtext.draw_line(regular, '', size=1.0, pixels_per_unit=32)
    assert line.image is None
