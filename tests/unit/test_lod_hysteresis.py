"""A level of detail that holds its level near a threshold, and bounds what it draws.

Pure Python -- no GL. A viewer standing at a switch distance, or bobbing
across one, would otherwise change level every frame: each change is a visible
pop and makes the pass re-walk its flattened scenegraph. So a node moves to a
coarser level only once the viewer is a fraction ``hysteresis`` past the
threshold, and back to the finer level at the threshold itself.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.lod import (
    CULLED, LOD, ScreenCoverageLOD, distance_to_viewer,
)
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform


def _levels(count=3):
    return [Transform() for _ in range(count)]


def _at(distance):
    """A modelview that puts the node's origin ``distance`` in front of the eye."""
    matrix = np.identity(4, dtype='d')
    matrix[3, 2] = -distance
    return matrix


class TestADistanceNodeNearARange:
    def test_the_first_choice_is_the_plain_answer(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])

        node.select(20.0)

        assert node.whichLevel == 2

    def test_jitter_across_a_range_does_not_flip_the_level(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])
        node.select(9.0)
        changes = [node.select(distance) for distance in
                   (10.2, 9.9, 10.4, 9.95, 10.3)]
        assert node.whichLevel == 0
        assert changes.count(True) == 0

    def test_going_out_waits_for_the_band(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])
        node.select(9.0)

        node.select(10.0 * (1.0 + node.hysteresis) - 0.01)
        assert node.whichLevel == 0
        node.select(10.0 * (1.0 + node.hysteresis) + 0.01)
        assert node.whichLevel == 1

    def test_coming_in_switches_at_the_range(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])
        node.select(15.0)
        assert node.whichLevel == 1

        node.select(10.05)
        assert node.whichLevel == 1
        node.select(9.99)
        assert node.whichLevel == 0

    def test_a_long_step_out_stops_where_the_band_allows(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])
        node.select(5.0)

        node.select(21.0)          # past 20, not past 22

        assert node.whichLevel == 1

    def test_no_hysteresis_is_the_plain_answer_every_time(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])
        node.hysteresis = 0.0
        node.select(9.0)
        node.select(10.0)
        assert node.whichLevel == 1


class TestACoverageNodeNearAThreshold:
    def _node(self):
        return ScreenCoverageLOD(level=_levels(), screenCoverage=[0.5, 0.2],
                                 radius=1.0)

    def test_oscillating_coverage_holds_the_level(self):
        node = self._node()
        node.show(node.levelForCoverage(0.6))
        held = [node.show(node.levelAt(1.0 / (0.5 + wobble), 1.0, 1.0))
                for wobble in (-0.02, 0.02, -0.03, 0.01, -0.01)]
        assert node.whichLevel == 0
        assert held.count(True) == 0

    def test_coarsening_waits_until_below_the_band(self):
        node = self._node()
        node.show(0)
        band = 0.5 * (1.0 - node.hysteresis)
        node.show(node.levelAt(1.0 / (band + 0.005), 1.0, 1.0))
        assert node.whichLevel == 0
        node.show(node.levelAt(1.0 / (band - 0.005), 1.0, 1.0))
        assert node.whichLevel == 1

    def test_refining_is_at_the_threshold(self):
        node = self._node()
        node.show(1)
        node.show(node.levelAt(1.0 / 0.51, 1.0, 1.0))
        assert node.whichLevel == 0

    def test_culling_waits_for_the_band_too(self):
        node = ScreenCoverageLOD(level=_levels(2), screenCoverage=[0.5, 0.2],
                                 radius=1.0)
        node.show(1)
        node.show(node.levelAt(1.0 / 0.19, 1.0, 1.0))
        assert node.whichLevel == 1
        node.show(node.levelAt(1.0 / 0.17, 1.0, 1.0))
        assert node.whichLevel == CULLED

    def test_hysteresis_is_held_short_of_the_whole_coverage(self):
        """A band reaching to zero coverage would never let the node coarsen."""
        node = self._node()
        node.hysteresis = 1.5
        node.show(0)
        node.show(node.levelAt(1.0 / 0.04, 1.0, 1.0))
        assert node.whichLevel == 1


def _box_levels():
    return [Shape(geometry=basenodes.Box(size=(1, 1, 1))),
            Shape(geometry=basenodes.Box(size=(10, 10, 10)))]


class TestTheBoundsOfWhatIsDrawn:
    @pytest.mark.parametrize('kind', [LOD, ScreenCoverageLOD])
    def test_a_new_level_is_bounded_by_its_own_geometry(self, kind):
        node = kind(level=_box_levels())
        assert list(node.boundingVolume().size) == pytest.approx([1, 1, 1])

        node.show(1)

        assert list(node.boundingVolume().size) == pytest.approx([10, 10, 10])

    def test_a_group_holding_it_is_rebounded_too(self):
        node = LOD(level=_box_levels())
        group = Group(children=[node])
        assert list(group.boundingVolume(None).size) == pytest.approx([1, 1, 1])

        node.show(1)

        assert list(group.boundingVolume(None).size) == pytest.approx([10, 10, 10])


class TestWhereACoverageNodeIsMeasuredFrom:
    def _placed(self):
        away = Transform(translation=(100, 0, 0), children=[
            Shape(geometry=basenodes.Box(size=(2, 2, 2)))])
        return ScreenCoverageLOD(level=[away], screenCoverage=[0.5])

    def test_a_measured_node_is_measured_from_its_geometry(self):
        node = self._placed()
        assert list(node.distanceCentre()) == pytest.approx([100, 0, 0])
        assert distance_to_viewer(node, _at(0.0)) == pytest.approx(100.0)

    def test_a_stated_centre_is_used_as_stated(self):
        node = self._placed()
        node.center = (0, 0, 5)
        assert list(node.distanceCentre()) == pytest.approx([0, 0, 5])

    def test_a_stated_radius_keeps_the_stated_centre(self):
        node = self._placed()
        node.radius = 1.0
        assert list(node.distanceCentre()) == pytest.approx([0, 0, 0])

    def test_a_distance_node_uses_its_centre_field(self):
        node = LOD(level=[Transform(translation=(100, 0, 0))])
        assert list(node.distanceCentre()) == pytest.approx([0, 0, 0])


class TestThePassMeasuresFromTheSamePoint:
    def test_the_pass_measures_a_measured_node_from_its_geometry(self):
        """The pass and :func:`distance_to_viewer` agree on the centre."""
        from OpenGLContext.passes import _flat
        from OpenGLContext.scenegraph import lod

        class Path(list):
            def transformMatrix(self):
                return np.identity(4, dtype='d')

        away = Transform(translation=(0, 0, -100), children=[
            Shape(geometry=basenodes.Box(size=(2, 2, 2)))])
        node = ScreenCoverageLOD(level=[away, Transform()],
                                 screenCoverage=[0.5, 0.0])
        rendering = _flat.FlatPass.__new__(_flat.FlatPass)
        rendering.paths = {lod.LOD: [Path([node])]}

        # The eye is two units from the geometry and a hundred from the origin.
        rendering.chooseLevels([lod.Viewer(_at(-98.0), 1.0)])

        assert node.whichLevel == 0
