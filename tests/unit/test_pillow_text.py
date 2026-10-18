"""Tests for pillowtext, which draws a line of text with Pillow.

``size`` is the face's em in the node's units. A line's image is its ink,
anti-aliased, at the pixels per unit asked, and its edges are given about
the line's origin on the baseline.
"""
import types

import numpy as np
import pytest
from vrml.vrml97 import basenodes

from OpenGLContext.scenegraph.text import pillowtext
from OpenGLContext.scenegraph.text.fontprovider import TTFFontProvider


@pytest.fixture(scope='module')
def regular():
    return pillowtext.face(basenodes.FontStyle(family=['SERIF']))


class Catalogue:
    """An installed-font registry holding exactly the faces it is given

    ``families`` maps a family name to its ``(path, weight, italic)`` faces.
    """

    STYLES = {'PLAIN': (400, 0), 'BOLD': (700, 0), 'ITALIC': (400, 1),
              'BOLDITALIC': (700, 1), 'LIGHT': (300, 0)}

    def __init__(self, families):
        self.families = families

    def modifiersFromStyle(self, fontStyle, mode=None):
        return self.STYLES[fontStyle.style]

    def fontNameFromStyle(self, fontStyle, mode=None):
        return fontStyle.family[0]

    def fontMembers(self, name):
        return [path for path, _weight, _italic in self.families[name]]

    def fontFile(self, member):
        return member

    def metadata(self, path):
        for faces in self.families.values():
            for found, weight, italic in faces:
                if found == path:
                    return types.SimpleNamespace(modifiers=(weight, italic))
        raise KeyError(path)


@pytest.fixture
def install(monkeypatch):
    """Replace the installed fonts with the families a test names"""
    def install(families, width=lambda path: pillowtext.NORMAL_WIDTH):
        monkeypatch.setattr(TTFFontProvider, 'getTTFRegistry',
                            staticmethod(lambda: Catalogue(families)))
        monkeypatch.setattr(pillowtext, '_width', width)
    return install


OPEN_SANS = {'Open Sans': [
    ('OpenSans-Light.ttf', 300, 0), ('OpenSans-CondLight.ttf', 300, 0),
    ('OpenSans-Regular.ttf', 400, 0), ('OpenSans-Italic.ttf', 400, 1),
    ('OpenSans-Bold.ttf', 700, 0), ('OpenSans-BoldItalic.ttf', 700, 1),
]}


@pytest.mark.parametrize('style, suffix', [
    ('PLAIN', 'Regular'), ('BOLD', 'Bold'), ('ITALIC', 'Italic'), ('BOLDITALIC', 'BoldItalic'),
])
def test_a_style_chooses_the_face(install, style, suffix):
    install(OPEN_SANS)
    found = pillowtext.face(basenodes.FontStyle(family=['Open Sans'], style=style))
    assert found.path == 'OpenSans-%s.ttf' % suffix
    assert not found.embolden and not found.oblique


def test_a_light_weight_is_the_family_s_own_width(install):
    """Of two faces at the weight asked, the one of normal width is chosen"""
    install(OPEN_SANS, width=lambda path: 3 if 'Cond' in path else pillowtext.NORMAL_WIDTH)
    found = pillowtext.face(basenodes.FontStyle(family=['Open Sans'], style='LIGHT'))
    assert found.path == 'OpenSans-Light.ttf'


def test_a_family_without_the_slant_is_sheared(install):
    install({'Serif': [('Serif.ttf', 400, 0), ('Serif-Bold.ttf', 700, 0)]})
    found = pillowtext.face(basenodes.FontStyle(family=['Serif'], style='BOLDITALIC'))
    assert found.path == 'Serif-Bold.ttf'
    assert found.oblique and not found.embolden


def test_a_family_without_the_weight_is_stroked_by_the_catalogue(install):
    install({'Serif': [('Serif.ttf', 400, 0)]})
    found = pillowtext.face(basenodes.FontStyle(family=['Serif'], style='BOLD'))
    assert found.path == 'Serif.ttf'
    assert found.embolden and not found.oblique


def test_a_family_without_the_weight_is_stroked():
    found = pillowtext.face(basenodes.FontStyle(family=['DejaVu Sans Mono'], style='BOLD'))
    assert found.path.endswith('DejaVuSansMono-Bold.ttf') and not found.embolden
    light = pillowtext.Face(found.path.replace('-Bold', ''), embolden=True)
    plain = pillowtext.draw_line(light._replace(embolden=False), 'l', 1.0, 64)
    bold = pillowtext.draw_line(light, 'l', 1.0, 64)
    assert np.asarray(bold.image)[:, :, 1].sum() > 1.2 * np.asarray(plain.image)[:, :, 1].sum()


def test_a_sheared_line_leans_right_above_the_baseline(regular):
    upright = pillowtext.draw_line(regular, 'l', 1.0, 64)
    leaning = pillowtext.draw_line(regular._replace(oblique=True), 'l', 1.0, 64)
    assert leaning.right > upright.right + 0.1
    alpha = np.asarray(leaning.image)[:, :, 1].astype(float)
    columns = np.arange(alpha.shape[1])
    top, bottom = alpha[: alpha.shape[0] // 4], alpha[-alpha.shape[0] // 4:]

    def centre(rows):
        return (rows.sum(axis=0) * columns).sum() / max(rows.sum(), 1)
    assert centre(top) > centre(bottom) + 5


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


def perspective(fov_y, near=0.1, far=100.0):
    """A row-vector perspective projection, as the engine's matrices are"""
    f = 1.0 / np.tan(fov_y / 2.0)
    m = np.zeros((4, 4))
    m[0, 0] = m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = -1.0
    m[3, 2] = 2.0 * far * near / (near - far)
    return m


def at_distance(distance):
    modelview = np.identity(4)
    modelview[3, 2] = -distance
    return modelview


def test_pixels_per_unit_on_screen():
    """A unit 10 away, under a 90 degree view 400 pixels high, is 20 pixels"""
    found = pillowtext.pixels_per_unit(at_distance(10.0), perspective(np.pi / 2), 400)
    assert found == pytest.approx(20.0, rel=0.01)
    assert pillowtext.pixels_per_unit(at_distance(20.0), perspective(np.pi / 2), 400) \
        == pytest.approx(10.0, rel=0.01)


def test_a_scaled_or_turned_text_is_measured_along_its_longer_axis():
    modelview = at_distance(10.0)
    modelview[0, 0] = 3.0                      # stretched along x
    found = pillowtext.pixels_per_unit(modelview, perspective(np.pi / 2), 400)
    assert found == pytest.approx(60.0, rel=0.01)


@pytest.mark.parametrize('pixels, expected', [
    (20.0, 22.627), (16.0, 16.0), (1.0, 8.0), (5000.0, 512.0),
])
def test_the_em_is_drawn_at_steps_of_half_an_octave(pixels, expected):
    """At least the em on screen, in steps of the square root of two,
    between 8 and 512 pixels"""
    assert pillowtext.em_pixels(pixels) == pytest.approx(expected, rel=0.001)


def test_the_steps_repeat_for_small_changes():
    assert pillowtext.em_pixels(18.0) == pillowtext.em_pixels(21.0)
