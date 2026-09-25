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
            def selectAt(self, distance, scale, tangent):
                raise ValueError('no centre')

        broken = _Broken(level=_levels(), range=[10.0])
        working = lod.LOD(level=_levels(), range=[10.0])

        _pass([broken, working]).selectLevels(_at(50.0))

        assert working.whichLevel == 1
        assert 'could not place an LOD node' in caplog.text

    def test_a_bad_node_is_reported_once_not_every_frame(self, caplog):
        class _Broken(lod.LOD):
            def selectAt(self, distance, scale, tangent):
                raise ValueError('no centre')

        rendering = _pass([_Broken(level=_levels(), range=[10.0])])
        for distance in (50.0, 40.0, 30.0):         # the camera moves each frame
            rendering.selectLevels(_at(distance))
        assert caplog.text.count('could not place an LOD node') == 1


class _MovablePath(list):
    """A path whose transform the test can change, as the scenegraph's would.

    The transform cache hands back the same matrix object while a node is
    unmoved and a fresh one once it moves, which is the signal the pass reads
    to tell whether last frame's answer still stands.
    """

    def __init__(self, nodes, matrix=None):
        super().__init__(nodes)
        self._matrix = np.identity(4, dtype='d') if matrix is None else matrix

    def transformMatrix(self):
        return self._matrix

    def moveTo(self, x):
        matrix = np.identity(4, dtype='d')
        matrix[3, 0] = x
        self._matrix = matrix


def _movable_pass(paths, field_of_view=60.0):
    rendering = _flat.FlatPass.__new__(_flat.FlatPass)
    rendering.paths = {lod.LOD: list(paths)}
    rendering.context = _Context(field_of_view)
    return rendering


class TestChoosingForEveryNodeInOnePass:
    """A frame decides a level for every level-of-detail node in the scene.

    Each decision is a handful of four-by-four products, and at that size a
    numpy call costs more than the arithmetic in it -- so the placing, the
    distances and the scales are worked out for the whole set at once and each
    node is handed its own numbers. What each node then does with them is its
    own: which threshold the coverage falls in, and whether the answer changed.
    """

    def _coverage_nodes(self, count=4):
        return [lod.ScreenCoverageLOD(
            level=_levels(), screenCoverage=[0.5, 0.2, 0.01], radius=1.0)
            for _ in range(count)]

    def test_each_node_is_placed_by_its_own_transform(self):
        near, far = self._coverage_nodes(2)
        paths = [_MovablePath([near]), _MovablePath([far])]
        paths[1].moveTo(60.0)

        _movable_pass(paths, field_of_view=90.0).selectLevels(_at(4.0))

        assert near.whichLevel < far.whichLevel

    def test_the_batch_chooses_what_one_at_a_time_chooses(self):
        for distance in (2.0, 5.0, 20.0, 200.0):
            together = self._coverage_nodes(3)
            _movable_pass([_MovablePath([n]) for n in together],
                          field_of_view=90.0).selectLevels(_at(distance))
            alone = lod.ScreenCoverageLOD(
                level=_levels(), screenCoverage=[0.5, 0.2, 0.01], radius=1.0)
            alone.selectFor(_at(distance), lod.viewer_tangent(90.0))
            assert [n.whichLevel for n in together] == [alone.whichLevel] * 3

    def test_a_still_camera_over_a_still_scene_works_nothing_out_again(self,
                                                                      monkeypatch):
        """The answer is last frame's answer, and reaching it costs a compare."""
        nodes = self._coverage_nodes(3)
        rendering = _movable_pass([_MovablePath([n]) for n in nodes])
        seen = []
        real = lod.uniform_scales
        monkeypatch.setattr(lod, 'uniform_scales',
                            lambda m: seen.append(len(m)) or real(m))

        for _frame in range(5):
            rendering.selectLevels(_at(4.0))

        assert seen == [3]

    def test_a_moved_camera_chooses_again(self, monkeypatch):
        nodes = self._coverage_nodes(2)
        rendering = _movable_pass([_MovablePath([n]) for n in nodes])
        seen = []
        real = lod.uniform_scales
        monkeypatch.setattr(lod, 'uniform_scales',
                            lambda m: seen.append(len(m)) or real(m))

        rendering.selectLevels(_at(4.0))
        rendering.selectLevels(_at(4.0))
        rendering.selectLevels(_at(90.0))

        assert seen == [2, 2]
        assert all(node.whichLevel > 0 for node in nodes)

    def test_a_node_that_moves_under_a_still_camera_chooses_again(self):
        near, far = self._coverage_nodes(2)
        paths = [_MovablePath([near]), _MovablePath([far])]
        rendering = _movable_pass(paths, field_of_view=90.0)

        rendering.selectLevels(_at(4.0))
        assert (near.whichLevel, far.whichLevel) == (1, 1)
        paths[1].moveTo(30.0)
        rendering.selectLevels(_at(4.0))

        assert (near.whichLevel, far.whichLevel) == (1, 2)

    def test_a_path_that_cannot_say_where_it_is_is_left_out(self, caplog):
        class _Unplaceable(_MovablePath):
            def transformMatrix(self):
                raise ValueError('a broken path')

        working = lod.LOD(level=_levels(), range=[10.0])

        _movable_pass([_Unplaceable([lod.LOD(level=_levels(), range=[10.0])]),
                       _MovablePath([working])]).selectLevels(_at(50.0))

        assert working.whichLevel == 1
        assert 'could not place an LOD node' in caplog.text
