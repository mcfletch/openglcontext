"""``colorSet`` compounds a Background's sky and ground stops into one set
(:mod:`OpenGLContext.scenegraph.spherebackground`).

The set is what ``buildSphere`` lays vertices along, so it has to come back
sorted by angle and bounded by the sphere: every angle in ``[0, pi]``, the
last one at ``pi``.  VRML97 puts no ceiling on ``skyAngle``, so a scene may
name stops past the south pole; those are past the far side of the sphere and
the visible sky ends at ``pi``, with the colour there interpolated between the
stops either side of it.

``tests/unit/test_background_uniform_sky.py`` covers the single-colour case.
"""
from math import pi

import pytest

from OpenGLContext.scenegraph.background import Background

BLUE = (0.0, 0.0, 1.0)
CYAN = (0.0, 1.0, 1.0)
WHITE = (1.0, 1.0, 1.0)


def _angles(background):
    found = background.colorSet()
    assert len(found), "colorSet gave nothing"
    return [float(stop[0]) for stop in found]


def _assert_spans_the_sphere(angles):
    assert angles == sorted(angles), angles
    assert angles[0] >= 0.0, angles
    assert abs(angles[-1] - pi) < 1e-5, angles
    assert max(angles) <= pi + 1e-5, angles


class TestSkyStopsWithinTheSphere:
    """The ordinary case: the last sky angle is short of the south pole."""

    def test_the_set_spans_the_sphere(self):
        _assert_spans_the_sphere(_angles(Background(
            skyColor=[BLUE, CYAN, WHITE], skyAngle=[1.0, 2.0],
        )))


class TestSkyStopsAtTheSouthPole:
    """A final stop at exactly ``pi`` names the whole sphere itself."""

    def test_the_set_spans_the_sphere(self):
        _assert_spans_the_sphere(_angles(Background(
            skyColor=[BLUE, CYAN], skyAngle=[pi],
        )))


class TestSkyStopsPastTheSouthPole:
    """An angle greater than ``pi`` is past the far side of the sphere.

    The set is cut at ``pi``, so nothing is left for ``buildSphere`` to lay a
    vertex beyond the pole at.
    """

    @pytest.mark.parametrize('angles', [
        [1.0, 4.0],
        [4.0, 5.0],
        [0.5, 3.0, 6.0],
    ])
    def test_the_set_stops_at_pi(self, angles):
        colours = [BLUE, CYAN, WHITE, (1.0, 0.0, 0.0)][:len(angles) + 1]
        _assert_spans_the_sphere(_angles(Background(
            skyColor=colours, skyAngle=angles,
        )))

    def test_the_colour_at_the_pole_lies_between_its_neighbours(self):
        """Cutting at ``pi`` interpolates rather than taking a stop's colour."""
        found = Background(skyColor=[BLUE, CYAN, WHITE], skyAngle=[1.0, 4.0]).colorSet()
        red = float(found[-1][1])
        assert 0.0 < red < 1.0, red


class TestSkyAndGroundPastTheSouthPole:
    """Ground stops cap the sky, and the cut at ``pi`` happens first."""

    def test_the_set_spans_the_sphere(self):
        _assert_spans_the_sphere(_angles(Background(
            skyColor=[BLUE, CYAN, WHITE], skyAngle=[1.0, 4.0],
            groundColor=[(0.2, 0.1, 0.0), (0.4, 0.2, 0.0)], groundAngle=[0.5],
        )))
