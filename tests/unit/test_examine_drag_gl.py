"""A right-drag through a real GL context, end to end (needs GL).

The whole chain the user's hand goes through: the selection pass decides what
was clicked, the context chooses a pivot from it, the orbit turns the drag into
a camera and the view platform draws it. The unit tests hold each piece; this
holds the thing they add up to, which is that a right-drag leaves the object you
were looking at on the screen, the right way up and the same distance away.

The behaviour this replaced, measured on the same code: a 30-pixel drag beginning
40 pixels from the edge of an 800-pixel window turned **135 degrees**, against
**7 degrees** for the same movement the other way, and 200 pixels of diagonal
drag left the camera's up vector at ``(-0.87, -0.50, 0.00)`` -- rolled and
upside down. See `plans/EXAMINE-NAVIGATION.md`.

Skips (rather than fails) where no GL target can be created.
"""
import subprocess
import sys

import pytest

from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.testing.paths import tests_root

DRIVER = tests_root(__file__) / 'helpers' / '_examine_drive.py'

#: The window the driver opens, and its middle.
WIDTH, HEIGHT = 400, 300
MIDDLE = (WIDTH // 2, HEIGHT // 2)

gl = pytest.mark.skipif(not gl_available(), reason='no GL target available')


def _drag(start, delta):
    """Right-drag from ``start`` by ``delta`` and return the reported lines."""
    result = subprocess.run(
        [sys.executable, str(DRIVER), str(start[0]), str(start[1]),
         str(delta[0]), str(delta[1])],
        capture_output=True, text=True, timeout=180,
    )
    assert 'GAVE UP' not in result.stdout, (
        'the drag never completed:\n%s\n%s' % (result.stdout, result.stderr))
    assert 'DONE' in result.stdout, (
        'driver did not finish:\n%s\n%s' % (result.stdout, result.stderr))
    reported = {}
    for line in result.stdout.splitlines():
        head, _, tail = line.partition(' ')
        reported[head] = tail
    return reported


@gl
class TestTheSameMovementTurnsTheSameAmount:
    """Where the drag began decided how far it turned; it no longer does."""

    def test_a_drag_near_the_left_edge_matches_one_from_the_middle(self):
        near = float(_drag((30, MIDDLE[1]), (-25, 0))['SWING'])
        middle = float(_drag(MIDDLE, (-25, 0))['SWING'])
        assert near == pytest.approx(middle, abs=0.01)

    def test_a_drag_near_the_right_edge_matches_one_from_the_middle(self):
        near = float(_drag((WIDTH - 30, MIDDLE[1]), (25, 0))['SWING'])
        middle = float(_drag(MIDDLE, (25, 0))['SWING'])
        assert near == pytest.approx(middle, abs=0.01)

    def test_the_two_directions_match(self):
        assert float(_drag(MIDDLE, (25, 0))['SWING']) == pytest.approx(
            float(_drag(MIDDLE, (-25, 0))['SWING']), abs=0.01)

    def test_a_small_drag_is_a_small_turn(self):
        assert float(_drag(MIDDLE, (25, 0))['SWING']) < 20.0


@gl
class TestTheObjectStaysWhereYouCanSeeIt:
    def test_a_diagonal_drag_leaves_the_model_on_screen(self):
        reported = _drag((225, 175), (60, 30))
        assert reported['ONSCREEN'] == 'True'

    def test_the_camera_stays_the_same_distance_from_the_pivot(self):
        before, after = _drag((225, 175), (60, 30))['DISTANCE'].split()
        assert float(after) == pytest.approx(float(before), abs=1e-4)

    def test_the_horizon_does_not_roll(self):
        """The camera's right axis stays in the horizontal plane."""
        assert abs(float(_drag((225, 175), (60, 30))['ROLL'])) < 1e-6

    def test_the_camera_is_still_the_right_way_up(self):
        assert float(_drag((225, 175), (60, 30))['LEVEL']) > 0.0


@gl
class TestGoingOverTheTop:
    def test_a_drag_far_past_the_pole_stops_short_of_it(self):
        reported = _drag(MIDDLE, (0, -4 * HEIGHT))
        assert float(reported['SWING']) < 90.0
        assert float(reported['LEVEL']) > 0.0, 'the view came out upside down'

    def test_it_is_the_same_going_the_other_way(self):
        reported = _drag(MIDDLE, (0, 4 * HEIGHT))
        assert float(reported['SWING']) < 90.0
        assert float(reported['LEVEL']) > 0.0


@gl
class TestWhatItOrbits:
    def test_clicking_the_model_pivots_on_the_model(self):
        """The box is two units across at the origin, so its front face is at
        z = 1 and that is what a click in the middle of it touches."""
        pivot = [float(value) for value in _drag(MIDDLE, (25, 0))['PIVOT'].split()]
        assert pivot[2] == pytest.approx(1.0, abs=0.05)
        assert abs(pivot[0]) < 0.05 and abs(pivot[1]) < 0.05

    def test_clicking_past_the_model_pivots_on_the_scene(self):
        """Not on the far plane, which is what unprojecting a miss gives."""
        pivot = [float(value)
                 for value in _drag((30, MIDDLE[1]), (-25, 0))['PIVOT'].split()]
        assert max(abs(value) for value in pivot) < 0.05
