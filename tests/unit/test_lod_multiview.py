"""One level of detail for a frame drawn through several cameras.

A level-of-detail node draws one level per frame, because choosing a level
replaces a subtree of the scene. With several views on screen the level is
the finest any of them asks for, so the closest view gets the detail it needs.

Pure Python -- no GL.
"""
import numpy as np
import pytest

from OpenGLContext.passes import _flat
from OpenGLContext.scenegraph import lod
from OpenGLContext.scenegraph.transform import Transform


class _Path(list):
    def __init__(self, nodes, x=0.0):
        super().__init__(nodes)
        self._matrix = np.identity(4, dtype='d')
        self._matrix[3, 0] = x

    def transformMatrix(self):
        return self._matrix


def _pass(nodes):
    rendering = _flat.FlatPass.__new__(_flat.FlatPass)
    rendering.paths = {lod.LOD: [_Path([node]) for node in nodes]}
    rendering.context = None
    return rendering


def _at(distance):
    matrix = np.identity(4, dtype='d')
    matrix[3, 2] = -distance
    return matrix


def _levels(count=3):
    return [Transform() for _ in range(count)]


def _coverage_node():
    return lod.ScreenCoverageLOD(
        level=_levels(), screenCoverage=[0.5, 0.2, 0.01], radius=1.0)


def _perspective(distance, degrees=90.0):
    return lod.Viewer(_at(distance), lod.viewer_tangent(degrees))


class TestALevelWithoutShowingIt:
    def test_a_distance_node_names_the_level_it_would_draw(self):
        node = lod.LOD(level=_levels(), range=[10.0, 20.0])
        assert node.levelAt(15.0, 1.0, 1.0) == 1
        assert node.whichLevel == 0

    def test_a_coverage_node_names_the_level_it_would_draw(self):
        node = _coverage_node()
        assert node.levelAt(4.0, 1.0, 1.0) == 1
        assert node.levelAt(1000.0, 1.0, 1.0) == lod.CULLED
        assert node.whichLevel == 0

    def test_a_coverage_node_with_nothing_to_measure_keeps_its_level(self):
        node = lod.ScreenCoverageLOD(level=[], screenCoverage=[0.5])
        node.whichLevel = 2
        assert node.levelAt(4.0, 1.0, 1.0) == 2


class TestTheFinestLevelAnyViewAsksFor:
    def test_the_close_view_decides(self):
        node = _coverage_node()
        _pass([node]).chooseLevels([_perspective(100.0), _perspective(4.0)])
        assert node.whichLevel == 1

    def test_a_node_culled_in_one_view_is_drawn_for_the_other(self):
        node = _coverage_node()
        _pass([node]).chooseLevels([_perspective(4.0), _perspective(1000.0)])
        assert node.whichLevel == 1

    def test_a_node_every_view_culls_is_culled(self):
        node = _coverage_node()
        _pass([node]).chooseLevels([_perspective(1000.0), _perspective(2000.0)])
        assert node.whichLevel == lod.CULLED

    def test_a_distance_node_follows_the_nearest_view(self):
        node = lod.LOD(level=_levels(), range=[10.0, 20.0])
        _pass([node]).chooseLevels([_perspective(30.0), _perspective(15.0)])
        assert node.whichLevel == 1

    def test_one_viewer_chooses_what_select_levels_chooses(self):
        for distance in (2.0, 5.0, 20.0, 200.0):
            chosen, selected = _coverage_node(), _coverage_node()
            _pass([chosen]).chooseLevels([_perspective(distance)])
            rendering = _pass([selected])

            class _Platform:
                frustum = (90.0, 1.0, 0.3, 1000.0)

            class _Context:
                def getViewPlatform(self):
                    return _Platform()

            rendering.context = _Context()
            rendering.selectLevels(_at(distance))
            assert chosen.whichLevel == selected.whichLevel

    def test_no_viewers_chooses_nothing(self):
        node = lod.LOD(level=_levels(), range=[10.0])
        node.whichLevel = 1
        _pass([node]).chooseLevels([])
        assert node.whichLevel == 1


class TestAnOrthographicView:
    def test_coverage_is_the_share_of_the_views_height(self):
        """A map view is the same size wherever the camera stands."""
        node = _coverage_node()
        # Half the view's height is 4 units; the node's radius is 1, so it
        # spans a quarter of the height, which is level 1's band.
        viewer = lod.Viewer(_at(500.0), 4.0, orthographic=True)
        _pass([node]).chooseLevels([viewer])
        assert node.whichLevel == 1

    def test_the_distance_to_an_orthographic_camera_changes_nothing(self):
        near, far = _coverage_node(), _coverage_node()
        _pass([near]).chooseLevels([lod.Viewer(_at(5.0), 4.0, orthographic=True)])
        _pass([far]).chooseLevels([lod.Viewer(_at(5000.0), 4.0, orthographic=True)])
        assert near.whichLevel == far.whichLevel == 1

    def test_zooming_out_coarsens(self):
        node = _coverage_node()
        _pass([node]).chooseLevels([lod.Viewer(_at(5.0), 40.0, orthographic=True)])
        assert node.whichLevel == 2


class TestTheLensOfACamera:
    def test_a_perspective_camera_gives_its_field_of_view(self):
        class _Camera:
            frustum = (60.0, 1.0, 0.1, 100.0)

        projection = np.identity(4)
        projection[2, 3] = -1.0
        projection[3, 3] = 0.0
        viewer = lod.viewer_for(_Camera(), _at(3.0), projection)
        assert not viewer.orthographic
        assert viewer.tangent == pytest.approx(lod.viewer_tangent(60.0))

    def test_an_orthographic_projection_gives_its_half_height(self):
        from OpenGLContext.passes.shadowmath import ortho_matrix

        projection = ortho_matrix(-8.0, 8.0, -4.0, 4.0, 0.0, 100.0)
        viewer = lod.viewer_for(object(), _at(3.0), projection)
        assert viewer.orthographic
        assert viewer.tangent == pytest.approx(4.0)

    def test_a_camera_that_cannot_say_reads_its_projection(self):
        projection = np.identity(4)
        projection[1, 1] = 2.0
        projection[2, 3] = -1.0
        projection[3, 3] = 0.0
        viewer = lod.viewer_for(object(), _at(3.0), projection)
        assert viewer.tangent == pytest.approx(0.5)


class TestTheMemo:
    def test_a_still_layout_works_nothing_out_again(self, monkeypatch):
        rendering = _pass([_coverage_node()])
        seen = []
        real = lod.uniform_scales
        monkeypatch.setattr(lod, 'uniform_scales',
                            lambda m: seen.append(len(m)) or real(m))
        viewers = [_perspective(4.0), _perspective(40.0)]
        for _frame in range(3):
            rendering.chooseLevels(viewers)
        assert len(seen) == 2          # one product per view, once

    def test_moving_any_view_chooses_again(self, monkeypatch):
        rendering = _pass([_coverage_node()])
        seen = []
        real = lod.uniform_scales
        monkeypatch.setattr(lod, 'uniform_scales',
                            lambda m: seen.append(len(m)) or real(m))
        rendering.chooseLevels([_perspective(4.0), _perspective(40.0)])
        rendering.chooseLevels([_perspective(4.0), _perspective(41.0)])
        assert len(seen) == 4

    def test_zooming_an_orthographic_view_chooses_again(self):
        node = _coverage_node()
        rendering = _pass([node])
        rendering.chooseLevels([lod.Viewer(_at(5.0), 4.0, orthographic=True)])
        rendering.chooseLevels([lod.Viewer(_at(5.0), 40.0, orthographic=True)])
        assert node.whichLevel == 2

    def test_a_new_range_chooses_again_with_nothing_moved(self):
        node = lod.LOD(level=_levels(), range=[10.0, 20.0])
        rendering = _pass([node])
        rendering.chooseLevels([_perspective(15.0)])
        assert node.whichLevel == 1
        node.range = [30.0, 40.0]
        rendering.chooseLevels([_perspective(15.0)])
        assert node.whichLevel == 0

    def test_a_new_centre_chooses_again(self):
        node = lod.LOD(level=_levels(), range=[10.0, 20.0])
        rendering = _pass([node])
        rendering.chooseLevels([_perspective(15.0)])
        node.center = (0.0, 0.0, 10.0)
        rendering.chooseLevels([_perspective(15.0)])
        assert node.whichLevel == 0

    def test_new_coverages_choose_again(self):
        node = _coverage_node()
        rendering = _pass([node])
        rendering.chooseLevels([_perspective(4.0)])
        assert node.whichLevel == 1
        node.screenCoverage = [0.01, 0.005, 0.001]
        rendering.chooseLevels([_perspective(4.0)])
        assert node.whichLevel == 0

    def test_a_new_radius_chooses_again(self):
        node = _coverage_node()
        rendering = _pass([node])
        rendering.chooseLevels([_perspective(4.0)])
        node.radius = 100.0
        rendering.chooseLevels([_perspective(4.0)])
        assert node.whichLevel == 0

    def test_new_levels_choose_again(self):
        node = lod.LOD(level=[Transform()], range=[10.0, 20.0])
        rendering = _pass([node])
        rendering.chooseLevels([_perspective(15.0)])
        assert node.whichLevel == 0
        node.level = _levels()
        rendering.chooseLevels([_perspective(15.0)])
        assert node.whichLevel == 1
