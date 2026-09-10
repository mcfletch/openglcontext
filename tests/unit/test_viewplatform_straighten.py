"""Levelling the camera keeps the direction it was facing.

``straighten`` drops any roll and pitch the view has picked up and leaves a
rotation about Y alone, so the horizon comes level without the player being
turned around.
"""
import math
from typing import Tuple

import pytest

from OpenGLContext.move.viewplatform import ViewPlatform, xytoa

#: Every 30 degrees of the compass, so each quadrant is covered.
YAWS = [math.radians(d) for d in range(0, 360, 30)]


def _forward(platform: ViewPlatform) -> Tuple[float, float, float]:
    return tuple(float(v) for v in (platform.quaternion * [0, 0, -1, 0])[:3])


class TestXYToA:
    @pytest.mark.parametrize('x,y', [
        (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (-1.0, 1.0),
        (-1.0, 0.0), (-1.0, -1.0), (0.0, -1.0), (1.0, -1.0),
        (-3.0, 0.5), (-0.5, -3.0),
    ])
    def test_it_is_the_angle_of_the_x_y_vector(self, x: float, y: float) -> None:
        """The answer is the vector's own bearing, to within a whole turn."""
        expected = math.atan2(y, x)
        got = xytoa(x, y)
        assert math.isclose(math.cos(got), math.cos(expected), abs_tol=1e-9)
        assert math.isclose(math.sin(got), math.sin(expected), abs_tol=1e-9)


class TestStraighten:
    @pytest.mark.parametrize('yaw', YAWS)
    def test_a_level_view_is_left_facing_the_same_way(self, yaw: float) -> None:
        """A camera with no roll or pitch is already straight; it must not turn."""
        platform = ViewPlatform(orientation=(0, 1, 0, yaw))
        before = _forward(platform)
        platform.straighten()
        after = _forward(platform)
        assert after == pytest.approx(before, abs=1e-6), (
            'straighten turned a level view from %r to %r' % (before, after))

    @pytest.mark.parametrize('yaw', YAWS)
    def test_pitch_is_removed_and_the_heading_kept(self, yaw: float) -> None:
        """Looking up 30 degrees then straightening keeps the compass bearing."""
        from OpenGLContext import quaternion
        platform = ViewPlatform(orientation=(0, 1, 0, yaw))
        pitched = platform.quaternion * quaternion.fromXYZR(1, 0, 0, math.radians(30))
        platform.quaternion = pitched
        bearing = _forward(platform)
        platform.straighten()
        after = _forward(platform)
        assert after[1] == pytest.approx(0.0, abs=1e-6), 'the view is level'
        # Compared as a direction, so +pi and -pi are the one bearing.
        length = math.hypot(bearing[0], bearing[2])
        assert (after[0], after[2]) == pytest.approx(
            (bearing[0] / length, bearing[2] / length), abs=1e-6)
