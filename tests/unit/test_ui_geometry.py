"""Rectangles and font measurement for the overlay UI.

Both are pure arithmetic, so they are tested with no GL context at all; the
drawing that uses them is tested separately against a real context.
"""

import pytest

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics


class TestRect:
    def test_a_point_inside_is_contained(self):
        assert Rect(10, 20, 30, 40).contains(11, 21)

    def test_the_far_edges_are_outside(self):
        """Half-open, so two abutting rectangles never both claim a pixel."""
        rect = Rect(10, 20, 30, 40)
        assert not rect.contains(40, 30)
        assert not rect.contains(30, 60)
        assert rect.contains(10, 20)

    def test_overlapping_rectangles_intersect(self):
        assert Rect(0, 0, 10, 10).intersects(Rect(5, 5, 10, 10))
        assert not Rect(0, 0, 10, 10).intersects(Rect(10, 0, 10, 10))

    def test_inset_shrinks_on_every_side(self):
        assert Rect(0, 0, 100, 50).inset(5) == Rect(5, 5, 90, 40)

    def test_inset_never_goes_negative(self):
        """A panel narrower than its own padding must not produce a -4 width."""
        assert Rect(0, 0, 6, 6).inset(5) == Rect(5, 5, 0, 0)

    def test_inset_takes_separate_sides(self):
        """Sides are named in the order left, top, right, bottom."""
        assert Rect(0, 0, 100, 50).inset(1, 2, 3, 4) == Rect(1, 4, 96, 44)

    def test_expand_grows_every_side(self):
        assert Rect(10, 10, 5, 5).expand(2) == Rect(8, 8, 9, 9)

    def test_offset_moves_without_resizing(self):
        assert Rect(1, 2, 3, 4).offset(10, 20) == Rect(11, 22, 3, 4)

    def test_clip_is_the_common_area(self):
        assert Rect(0, 0, 10, 10).clip(Rect(5, 5, 10, 10)) == Rect(5, 5, 5, 5)

    def test_clip_of_disjoint_rectangles_is_empty(self):
        clipped = Rect(0, 0, 10, 10).clip(Rect(50, 50, 10, 10))
        assert clipped.empty
        assert clipped.width == 0 and clipped.height == 0

    def test_centre_is_the_middle(self):
        assert Rect(0, 0, 10, 20).centre == (5, 10)

    def test_an_empty_rect_contains_nothing(self):
        assert not Rect(0, 0, 0, 10).contains(0, 5)


class TestFontMetrics:
    @pytest.fixture
    def metrics(self):
        return FontMetrics(char_width=8, char_height=16)

    def test_a_line_is_as_wide_as_its_characters(self, metrics):
        assert metrics.text_width('abcd') == 32

    def test_an_empty_string_measures_zero(self, metrics):
        assert metrics.text_size('') == (0, 0)

    def test_multiple_lines_take_the_widest_and_stack(self, metrics):
        width, height = metrics.text_size('ab\nabcd')
        assert width == 32
        assert height == 2 * metrics.line_height

    def test_line_height_includes_the_gap(self):
        assert FontMetrics(8, 16, line_gap=4).line_height == 20

    def test_wrapping_breaks_between_words(self, metrics):
        # 10 characters fit in 80 pixels.
        assert metrics.wrap('hello there world', 80) == ['hello', 'there', 'world']

    def test_wrapping_fills_each_line(self, metrics):
        assert metrics.wrap('a b c d e', 8 * 5) == ['a b c', 'd e']

    def test_a_word_longer_than_the_line_is_broken(self, metrics):
        """Better a split word than text running out past the panel edge."""
        assert metrics.wrap('abcdefgh', 8 * 3) == ['abc', 'def', 'gh']

    def test_wrapping_keeps_explicit_line_breaks(self, metrics):
        assert metrics.wrap('a\nb', 800) == ['a', 'b']

    def test_wrapping_a_blank_line_keeps_it(self, metrics):
        assert metrics.wrap('a\n\nb', 800) == ['a', '', 'b']

    def test_wrapping_to_no_width_gives_one_word_per_line(self, metrics):
        assert metrics.wrap('ab cd', 0) == ['ab', 'cd']

    def test_truncation_marks_what_it_dropped(self, metrics):
        assert metrics.truncate('abcdefgh', 8 * 5) == 'abcd…'

    def test_truncation_leaves_text_that_fits(self, metrics):
        assert metrics.truncate('abc', 8 * 5) == 'abc'

    def test_truncation_to_nothing_is_empty(self, metrics):
        assert metrics.truncate('abc', 0) == ''
