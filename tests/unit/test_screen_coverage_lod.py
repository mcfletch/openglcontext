"""Choosing a level of detail by how much of the screen the object covers.

Pure Python -- no GL. ``MSFT_lod`` names its levels finest first and gives each
one the screen coverage at which it takes over, so a level is drawn from its own
threshold up to the previous one, and below the last threshold nothing is drawn
at all. Coverage is a share of the viewport's height, which is why the viewer's
field of view is part of the answer and a distance on its own is not.
"""
import math

import numpy as np
import pytest
from pydispatch import dispatcher

from OpenGLContext.scenegraph import lod
from OpenGLContext.scenegraph.lod import (
    CULLED, LOD, ScreenCoverageLOD, screen_fraction, uniform_scale,
)
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.switch import SWITCH_CHANGE_SIGNAL
from OpenGLContext.scenegraph.transform import Transform
from OpenGLContext.scenegraph import basenodes

#: 90 degrees of vertical field of view, where a unit sphere one unit away
#: fills the window from top to bottom and the arithmetic stays checkable.
SQUARE = 1.0


def _levels(count=3):
    return [Transform() for _ in range(count)]


def _node(thresholds=(0.5, 0.2, 0.01), radius=1.0, levels=3):
    return ScreenCoverageLOD(
        level=_levels(levels), screenCoverage=list(thresholds), radius=radius)


class _Listener(object):
    """Something that hears a level change and stays alive to report it.

    The dispatcher holds its receivers weakly, so a test that connects a
    throwaway function hears nothing.
    """

    def __init__(self, node):
        self.seen = []
        dispatcher.connect(self.note, signal=SWITCH_CHANGE_SIGNAL, sender=node)

    def note(self, value):
        self.seen.append(value)


def _at(distance):
    """The modelview of a viewer ``distance`` away down -Z, row-vector."""
    matrix = np.identity(4, dtype='d')
    matrix[3, 2] = -distance
    return matrix


class TestWhatAnObjectCoversOnScreen:
    def test_a_sphere_spans_the_window_when_its_diameter_does(self):
        """Half the window's height at distance d is d*tan(fov/2)."""
        assert screen_fraction(1.0, 1.0, SQUARE) == pytest.approx(1.0)

    def test_coverage_falls_off_with_distance(self):
        assert screen_fraction(1.0, 4.0, SQUARE) == pytest.approx(0.25)

    def test_a_narrower_field_of_view_magnifies(self):
        """Half the fov is (about) twice the size on screen."""
        narrow = math.tan(math.radians(30.0) / 2.0)
        assert screen_fraction(1.0, 10.0, narrow) > screen_fraction(1.0, 10.0, SQUARE)

    def test_nothing_covers_more_than_the_whole_window(self):
        assert screen_fraction(1.0, 0.001, SQUARE) == 1.0

    def test_a_viewer_inside_the_object_covers_the_window(self):
        assert screen_fraction(1.0, 0.0, SQUARE) == 1.0


class TestHowMuchATransformMagnifies:
    def test_an_untransformed_node_is_its_own_size(self):
        assert uniform_scale(np.identity(4)) == pytest.approx(1.0)

    def test_a_scaled_node_is_bigger_by_its_scale(self):
        matrix = np.identity(4, dtype='d')
        matrix[0, 0] = matrix[1, 1] = matrix[2, 2] = 3.0
        assert uniform_scale(matrix) == pytest.approx(3.0)

    def test_the_largest_axis_is_what_shows(self):
        """An object stretched on one axis is as big as its biggest extent."""
        matrix = np.identity(4, dtype='d')
        matrix[1, 1] = 5.0
        assert uniform_scale(matrix) == pytest.approx(5.0)

    def test_translation_is_not_scale(self):
        assert uniform_scale(_at(100.0)) == pytest.approx(1.0)


class TestChoosingALevelByCoverage:
    @pytest.mark.parametrize('coverage,wanted', [
        (1.0, 0), (0.6, 0), (0.5, 0),
        (0.49, 1), (0.2, 1),
        (0.19, 2), (0.01, 2),
        (0.009, CULLED), (0.0, CULLED),
    ])
    def test_each_threshold_hands_over_to_the_next_level(self, coverage, wanted):
        """The spec's own example: 1.0-0.5, 0.5-0.2, 0.2-0.01, then nothing."""
        assert _node().levelForCoverage(coverage) == wanted

    def test_below_the_last_threshold_nothing_is_drawn(self):
        node = _node()

        node.show(node.levelForCoverage(0.001))

        assert node.whichLevel == CULLED
        assert node.renderedChildren() == []

    def test_with_no_thresholds_the_finest_level_stands(self):
        """A file that named none is a file asking for its own geometry."""
        assert _node(thresholds=()).levelForCoverage(0.0) == 0

    def test_fewer_thresholds_than_levels_never_culls(self):
        node = _node(thresholds=(0.5,), levels=3)

        assert node.levelForCoverage(1e-9) == 1

    def test_more_thresholds_than_levels_culls_at_the_last_level(self):
        node = _node(thresholds=(0.5, 0.2, 0.01), levels=2)

        assert node.levelForCoverage(0.1) == CULLED


class TestChoosingFromWhereTheViewerIs:
    def test_a_close_viewer_gets_the_finest_level(self):
        node = _node()

        node.selectFor(_at(1.5), SQUARE)

        assert node.whichLevel == 0
        assert node.renderedChildren() == [node.level[0]]

    def test_backing_away_coarsens(self):
        node = _node()

        node.selectFor(_at(3.0), SQUARE)     # coverage 1/3 -> level 1

        assert node.whichLevel == 1

    def test_far_enough_away_nothing_is_drawn(self):
        node = _node()

        node.selectFor(_at(1000.0), SQUARE)

        assert node.whichLevel == CULLED

    def test_a_scaled_node_holds_its_detail_longer(self):
        """Ten times the size is ten times the distance at the same level."""
        scaled = np.identity(4, dtype='d')
        scaled[0, 0] = scaled[1, 1] = scaled[2, 2] = 10.0
        scaled[3, 2] = -20.0
        big, small = _node(), _node()

        big.selectFor(scaled, SQUARE)
        small.selectFor(_at(20.0), SQUARE)

        assert big.whichLevel == 0
        assert small.whichLevel == 2

    def test_the_centre_is_where_the_distance_is_measured_to(self):
        """A level's centre, not the world origin: an off-centre model is
        judged by where the model is."""
        node = _node()
        node.center = (0, 0, 100)

        node.selectFor(_at(101.5), SQUARE)

        assert node.whichLevel == 0

    def test_choosing_the_same_level_again_is_not_a_change(self):
        node = _node()

        assert node.selectFor(_at(3.0), SQUARE) is True
        assert node.selectFor(_at(3.1), SQUARE) is False

    def test_a_change_of_level_announces_itself(self):
        """The pass keeps a flattened scenegraph; a level nobody told it about
        would not be drawn."""
        node = _node()
        listener = _Listener(node)

        node.selectFor(_at(1.5), SQUARE)
        node.selectFor(_at(3.0), SQUARE)

        assert listener.seen == [node.level[1]]

    def test_being_culled_announces_itself_as_nothing(self):
        node = _node()
        listener = _Listener(node)

        node.selectFor(_at(1000.0), SQUARE)

        assert listener.seen == [None]


class TestTheSizeItIsJudgedBy:
    def test_an_unset_radius_is_taken_from_the_geometry(self):
        """A file need not say how big it is: the finest level knows."""
        box = basenodes.Box(size=(2, 2, 2))
        node = ScreenCoverageLOD(
            level=[Shape(geometry=box)], screenCoverage=[0.5], radius=0.0)

        assert node.coverageRadius() == pytest.approx(math.sqrt(3.0))

    def test_a_stated_radius_is_used_as_stated(self):
        node = _node(radius=7.0)

        assert node.coverageRadius() == pytest.approx(7.0)

    def test_a_node_with_nothing_to_measure_keeps_its_finest_level(self):
        node = ScreenCoverageLOD(level=[], screenCoverage=[0.5], radius=0.0)

        assert node.selectFor(_at(10.0), SQUARE) is False
        assert node.renderedChildren() == []


class TestWhatACulledNodeStillBounds:
    def test_a_culled_node_is_bounded_by_the_level_it_would_draw(self):
        """Drawing nothing is not being everywhere: a parent group culls by
        this, and an unbounded volume would defeat it."""
        node = ScreenCoverageLOD(
            level=[Shape(geometry=basenodes.Box(size=(2, 2, 2)))],
            screenCoverage=[0.5], radius=1.0)

        node.show(CULLED)
        volume = node.boundingVolume()

        assert list(volume.size) == pytest.approx([2, 2, 2])


class TestTheDistanceNodeIsUnchanged:
    def test_a_vrml_lod_still_chooses_by_range(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])

        node.selectFor(_at(15.0), SQUARE)

        assert node.whichLevel == 1

    def test_a_vrml_lod_never_culls(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])

        node.selectFor(_at(1e6), SQUARE)

        assert node.whichLevel == 2


class TestTheWholeSceneAtOnce:
    """The same arithmetic, asked of every node in one pass.

    A frame decides a level for every level-of-detail node in the scene, and
    each decision is a matrix product and a length over four-by-four arrays --
    the size at which numpy's cost is the call rather than the arithmetic. The
    plural forms are what the pass uses; they have to give the singular ones'
    answers exactly, or a scene would switch levels differently from a node
    asked on its own.
    """

    def _views(self):
        turn = np.identity(4)
        turn[0, 0] = turn[2, 2] = math.cos(0.7)
        turn[0, 2], turn[2, 0] = math.sin(0.7), -math.sin(0.7)
        bigger = np.identity(4)
        bigger[0, 0] = bigger[1, 1] = bigger[2, 2] = 2.5
        return [_at(4.0), _at(100.0), turn @ _at(12.0), bigger @ _at(9.0)]

    def test_distances_match_one_at_a_time(self):
        node = _node()
        views = self._views()
        found = lod.viewer_distances(
            np.tile(np.asarray(node.center, dtype='d')[:3], (len(views), 1)),
            np.stack(views))
        assert found == pytest.approx(
            [lod.distance_to_viewer(node, view) for view in views])

    def test_a_nodes_own_centre_is_used(self):
        """Each node is placed by its own centre, not by the first one's."""
        centres = np.array([[0.0, 0.0, 0.0], [0.0, 3.0, 0.0]])
        views = np.stack([_at(4.0), _at(4.0)])
        found = lod.viewer_distances(centres, views)
        assert found[0] == pytest.approx(4.0)
        assert found[1] == pytest.approx(5.0)

    def test_scales_match_one_at_a_time(self):
        views = self._views()
        assert lod.uniform_scales(np.stack(views)) == pytest.approx(
            [uniform_scale(view) for view in views])

    def test_fractions_match_one_at_a_time(self):
        radii = np.array([1.0, 2.0, 0.5])
        distances = np.array([4.0, 0.25, 100.0])
        assert lod.screen_fractions(radii, distances, SQUARE) == pytest.approx(
            [screen_fraction(r, d, SQUARE)
             for r, d in zip(radii, distances)])

    def test_a_viewer_inside_the_sphere_covers_the_window(self):
        found = lod.screen_fractions(np.array([1.0, 1.0]),
                                     np.array([0.25, 8.0]), SQUARE)
        assert found[0] == 1.0 and found[1] < 1.0

    def test_nothing_to_choose_for_is_an_empty_answer(self):
        assert len(lod.viewer_distances(np.zeros((0, 3)),
                                        np.zeros((0, 4, 4)))) == 0
        assert len(lod.uniform_scales(np.zeros((0, 4, 4)))) == 0


class TestChoosingFromNumbersAlreadyWorkedOut:
    """``selectAt`` is the decision once the distance and the scale are known.

    The pass works those out for the whole scene in one pass and hands each
    node its own, so the node is left with the part that is genuinely its own:
    which of its thresholds the coverage falls in, and whether that is a
    change worth announcing.
    """

    def test_a_coverage_node_chooses_as_selectFor_would(self):
        for distance in (2.0, 4.0, 9.0, 40.0, 400.0):
            one, other = _node(), _node()
            one.selectFor(_at(distance), SQUARE)
            other.selectAt(distance, 1.0, SQUARE)
            assert one.whichLevel == other.whichLevel

    def test_a_magnified_node_is_told_by_its_scale(self):
        """A transform that makes the object bigger holds a finer level."""
        plain, magnified = _node(), _node()
        bigger = np.identity(4)
        bigger[0, 0] = bigger[1, 1] = bigger[2, 2] = 8.0
        plain.selectAt(40.0, 1.0, SQUARE)
        magnified.selectAt(40.0, uniform_scale(bigger), SQUARE)
        assert (plain.whichLevel, magnified.whichLevel) == (2, 1)

    def test_a_node_with_no_size_keeps_its_finest_level(self):
        node = ScreenCoverageLOD(level=_levels(), screenCoverage=[0.5],
                                 radius=0.0)
        node._measured = 0.0
        assert node.selectAt(50.0, 1.0, SQUARE) is False
        assert node.whichLevel == 0

    def test_a_vrml_node_reads_the_distance_and_ignores_the_rest(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])
        node.selectAt(15.0, 99.0, SQUARE)
        assert node.whichLevel == 1

    def test_an_unchanged_level_is_not_announced(self):
        node = _node()
        node.selectAt(4.0, 1.0, SQUARE)
        listener = _Listener(node)
        assert node.selectAt(4.0, 1.0, SQUARE) is False
        assert listener.seen == []
