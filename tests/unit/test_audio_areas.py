"""How loud an area's sound is from where the listener stands."""

import pytest

from OpenGLContext.audio.areas import box_gain

CENTRE = (0.0, 0.0, 0.0)
HALF = (10.0, 5.0, 10.0)


class TestBoxGain:
    def test_inside_the_box_it_is_full(self):
        assert box_gain((3.0, 1.0, -4.0), CENTRE, HALF) == 1.0

    def test_on_the_face_it_is_still_full(self):
        assert box_gain((10.0, 0.0, 0.0), CENTRE, HALF) == 1.0

    def test_it_fades_linearly_across_the_margin(self):
        assert box_gain((11.5, 0.0, 0.0), CENTRE, HALF, margin=3.0) == \
            pytest.approx(0.5)

    def test_past_the_margin_it_is_silent(self):
        assert box_gain((13.0, 0.0, 0.0), CENTRE, HALF, margin=3.0) == 0.0
        assert box_gain((0.0, 0.0, 80.0), CENTRE, HALF) == 0.0

    def test_the_furthest_axis_decides(self):
        """Outside on one axis is outside, however central the others are."""
        assert box_gain((0.0, 6.5, 12.0), CENTRE, HALF, margin=4.0) == \
            pytest.approx(0.5)

    def test_a_view_platform_position_is_accepted(self):
        """``ViewPlatform.position`` is homogeneous, (x, y, z, 1)."""
        assert box_gain((11.5, 0.0, 0.0, 1.0), CENTRE, HALF, margin=3.0) == \
            pytest.approx(0.5)

    def test_a_zero_margin_is_a_hard_edge(self):
        assert box_gain((10.0, 0.0, 0.0), CENTRE, HALF, margin=0.0) == 1.0
        assert box_gain((10.01, 0.0, 0.0), CENTRE, HALF, margin=0.0) == 0.0

    def test_it_returns_a_plain_float(self):
        assert type(box_gain(CENTRE, CENTRE, HALF)) is float
