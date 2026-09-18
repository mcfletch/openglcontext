"""The render pass telling every level-of-detail node where the viewer is.

Pure Python -- no GL. Once a frame, before the scene is walked, each ``LOD`` is
given the modelview that places it and the field of view it is seen through: a
VRML97 node has ranges and needs only the first, and an ``MSFT_lod`` node
switches on how much of the window the object covers and needs both.
"""
import math

import numpy as np
import pytest

from OpenGLContext.passes import _flat
from OpenGLContext.scenegraph import lod
from OpenGLContext.scenegraph.transform import Transform


class _Path(list):
    """The least of a NodePath the pass asks of it."""

    def transformMatrix(self):
        return np.identity(4, dtype='d')


class _ViewPlatform:
    def __init__(self, field_of_view):
        #: degrees, aspect, near, far -- the order gluPerspective takes them.
        self.frustum = (field_of_view, 1.0, 0.3, 50000.0)


class _Context:
    def __init__(self, field_of_view=60.0):
        self._platform = _ViewPlatform(field_of_view)

    def getViewPlatform(self):
        return self._platform


def _pass(paths, field_of_view=60.0):
    rendering = _flat.FlatPass.__new__(_flat.FlatPass)
    rendering.paths = {lod.LOD: [_Path([node]) for node in paths]}
    rendering.context = _Context(field_of_view)
    return rendering


def _at(distance):
    matrix = np.identity(4, dtype='d')
    matrix[3, 2] = -distance
    return matrix


def _levels(count=3):
    return [Transform() for _ in range(count)]


class TestDrivingTheNodes:
    def test_a_vrml_node_is_chosen_by_distance(self):
        node = lod.LOD(level=_levels(), range=[10.0, 20.0])

        _pass([node]).selectLevels(_at(15.0))

        assert node.whichLevel == 1

    def test_a_coverage_node_is_chosen_by_what_it_covers(self):
        node = lod.ScreenCoverageLOD(
            level=_levels(), screenCoverage=[0.5, 0.2, 0.01], radius=1.0)

        _pass([node], field_of_view=90.0).selectLevels(_at(4.0))

        assert node.whichLevel == 1

    def test_a_narrower_field_of_view_holds_a_finer_level(self):
        """The same object at the same distance fills more of a zoomed window."""
        wide = lod.ScreenCoverageLOD(
            level=_levels(), screenCoverage=[0.5, 0.2, 0.01], radius=1.0)
        narrow = lod.ScreenCoverageLOD(
            level=_levels(), screenCoverage=[0.5, 0.2, 0.01], radius=1.0)

        _pass([wide], field_of_view=90.0).selectLevels(_at(4.0))
        _pass([narrow], field_of_view=30.0).selectLevels(_at(4.0))

        assert wide.whichLevel == 1
        assert narrow.whichLevel == 0

    def test_every_node_is_asked(self):
        first = lod.LOD(level=_levels(), range=[10.0])
        second = lod.LOD(level=_levels(), range=[10.0])

        _pass([first, second]).selectLevels(_at(50.0))

        assert (first.whichLevel, second.whichLevel) == (1, 1)

    def test_a_scene_with_no_levels_of_detail_does_nothing(self):
        rendering = _flat.FlatPass.__new__(_flat.FlatPass)
        rendering.paths = {}

        assert rendering.selectLevels(_at(1.0)) is None


class TestWhatTheWindowMakesOfASize:
    @pytest.mark.parametrize('degrees', [30.0, 60.0, 90.0])
    def test_the_tangent_is_half_the_field_of_view(self, degrees):
        assert lod.viewer_tangent(degrees) == pytest.approx(
            math.tan(math.radians(degrees) / 2.0))

    def test_a_context_that_cannot_say_is_taken_as_the_usual_lens(self):
        """A pass drawing to something with no view platform still chooses a
        level, rather than failing the frame over a number it can default."""
        node = lod.ScreenCoverageLOD(
            level=_levels(), screenCoverage=[0.5, 0.2, 0.01], radius=1.0)
        rendering = _flat.FlatPass.__new__(_flat.FlatPass)
        rendering.paths = {lod.LOD: [_Path([node])]}
        rendering.context = None

        rendering.selectLevels(_at(4.0))

        assert node.whichLevel == 1


class TestAMalformedNode:
    def test_one_bad_node_does_not_stop_the_others(self, caplog):
        class _Broken(lod.LOD):
            def selectFor(self, modelview, tangent):
                raise ValueError('no centre')

        broken = _Broken(level=_levels(), range=[10.0])
        working = lod.LOD(level=_levels(), range=[10.0])

        _pass([broken, working]).selectLevels(_at(50.0))

        assert working.whichLevel == 1
        assert 'could not place an LOD node' in caplog.text
