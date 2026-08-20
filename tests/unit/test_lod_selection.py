"""Choosing a level of detail by how far away the viewer is.

Pure Python -- no GL. VRML97's ``LOD`` names its levels finest-first and gives
``range`` the distances between them, so ``range[i]`` is where level ``i`` gives
way to level ``i + 1``; ``center`` is the point in the node's own coordinates
those distances are measured to.
"""
import numpy as np
import pytest
from pydispatch import dispatcher

from OpenGLContext.scenegraph.lod import LOD
from OpenGLContext.scenegraph.switch import SWITCH_CHANGE_SIGNAL
from OpenGLContext.scenegraph.transform import Transform


def _levels(count=3):
    return [Transform() for _ in range(count)]


class TestChoosingALevel:
    def test_the_finest_level_is_used_close_up(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])

        node.select(0.0)

        assert node.whichLevel == 0
        assert node.renderedChildren() == [node.level[0]]

    @pytest.mark.parametrize('distance,wanted', [
        (0.0, 0), (9.99, 0), (10.0, 1), (15.0, 1), (20.0, 2), (1e6, 2),
    ])
    def test_each_range_hands_over_to_the_next_level(self, distance, wanted):
        node = LOD(level=_levels(), range=[10.0, 20.0])

        node.select(distance)

        assert node.whichLevel == wanted

    def test_with_no_ranges_the_finest_level_stands(self):
        """VRML97 leaves an empty range to the browser; the finest is honest."""
        node = LOD(level=_levels(), range=[])

        node.select(1e6)

        assert node.whichLevel == 0

    def test_more_ranges_than_levels_never_names_a_level_that_is_not_there(self):
        node = LOD(level=_levels(2), range=[10.0, 20.0, 30.0])

        node.select(1e6)

        assert node.whichLevel == 1

    def test_fewer_ranges_than_levels_leaves_the_last_ones_unused(self):
        node = LOD(level=_levels(4), range=[10.0])

        node.select(1e6)

        assert node.whichLevel == 1

    def test_a_node_with_no_levels_renders_nothing(self):
        node = LOD(level=[], range=[])

        node.select(5.0)

        assert node.renderedChildren() == []


class _Listener:
    """Something to hang a receiver on.

    The dispatcher holds its receivers weakly, so a test that connects a
    throwaway function hears nothing: what it connected is collected before the
    signal is sent. An object the test keeps does not go anywhere.
    """

    def __init__(self, node):
        self.seen = []
        dispatcher.connect(self.note, signal=SWITCH_CHANGE_SIGNAL, sender=node)

    def note(self, value):
        self.seen.append(value)


class TestTellingTheRendererItChanged:
    def _watch(self, node):
        return _Listener(node)

    def test_changing_level_says_so(self):
        """The pass keeps a flattened scenegraph; a level it never heard about
        swapping in would not be drawn."""
        node = LOD(level=_levels(), range=[10.0, 20.0])
        node.select(0.0)
        heard = self._watch(node)

        node.select(15.0)

        assert heard.seen == [node.level[1]]

    def test_staying_on_one_level_says_nothing(self):
        node = LOD(level=_levels(), range=[10.0, 20.0])
        node.select(12.0)
        heard = self._watch(node)

        node.select(13.0)
        node.select(19.9)

        assert heard.seen == []


class TestWhereTheDistanceIsMeasuredFrom:
    def test_the_centre_is_in_the_nodes_own_coordinates(self):
        """A figure's LOD sits at the figure, not at the world origin."""
        node = LOD(level=_levels(), range=[10.0], center=(0.0, 3.0, 0.0))

        assert tuple(node.center) == (0.0, 3.0, 0.0)

    def test_the_distance_of_a_placed_node_uses_that_centre(self):
        from OpenGLContext.scenegraph.lod import distance_to_viewer

        node = LOD(level=_levels(), range=[10.0], center=(0.0, 0.0, -4.0))
        # Local -> eye: shifted six along -z, so the centre sits ten away.
        modelview = np.identity(4)
        modelview[3, 2] = -6.0

        assert distance_to_viewer(node, modelview) == pytest.approx(10.0)


class TestAgainstTheRenderer:
    """A level chosen has to be a level *drawn*.

    The pass renders from a flattened scenegraph, so a node that picked a
    different level without the pass hearing about it would keep drawing the
    old one. The levels here differ by colour, so what comes back off the
    framebuffer says which one was drawn.
    """

    def _report(self):
        import os
        import subprocess
        import sys

        from OpenGLContext.testing.paths import tests_root

        harness = os.path.join(str(tests_root(__file__)), 'helpers',
                               '_lod_harness.py')
        result = subprocess.run([sys.executable, harness], capture_output=True,
                                text=True, timeout=300)
        if result.returncode != 0:
            raise AssertionError('LOD harness failed:\n%s\n%s'
                                 % (result.stdout[-3000:], result.stderr[-3000:]))
        return dict(line.split('=', 1) for line in result.stdout.strip().split('\n')
                    if '=' in line)

    def test_the_level_drawn_follows_the_viewer(self):
        report = self._report()

        assert report['near_level'] == '0'
        assert report['far_level'] == '1'
        near = [int(v) for v in report['near'].split(',')]
        far = [int(v) for v in report['far'].split(',')]
        assert near[0] > 200 and near[2] < 60, near   # the fine level is red
        assert far[2] > 200 and far[0] < 60, far      # the coarse one is blue
