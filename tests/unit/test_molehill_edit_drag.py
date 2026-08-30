"""Dragging a NURBS control point, end to end through a real pick (needs GL).

The editing demo's own chain: a click resolves to a control-point marker, a
press on a gizmo arm resolves to an axis, and the drag that follows moves the
point along that axis and no other, writing it back into the surface.  All of
it runs in a subprocess with a real GL context, because the node paths a drag
is measured through are what the selection pass produces and nothing else.

Skips (rather than fails) where no GL target can be created.
"""
import subprocess
import sys

import pytest

from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.testing.paths import tests_root

DRIVER = tests_root(__file__) / 'helpers' / '_molehill_edit_driver.py'

#: Which surface and control point the driver takes hold of, and how far it
#: drags.  Point 5 is a corner of the raised middle of the red hill, so the
#: surface visibly follows it.
NET, POINT, DISTANCE = 0, 5, 4.0

gl = pytest.mark.skipif(not gl_available(), reason='no GL target available')


def _drive(axis):
    """Run the driver for one axis and return its output as a dict of lines."""
    result = subprocess.run(
        [sys.executable, str(DRIVER), str(NET), str(POINT), str(axis),
         str(DISTANCE)],
        capture_output=True, text=True, timeout=180,
    )
    assert 'GAVE UP' not in result.stdout, (
        'the drag never completed:\n%s\n%s' % (result.stdout, result.stderr))
    assert 'DONE' in result.stdout, (
        'driver did not finish:\n%s\n%s' % (result.stdout, result.stderr))
    lines = {}
    for line in result.stdout.splitlines():
        head, _, tail = line.partition(' ')
        lines[head] = tail
    return lines


@gl
@pytest.mark.parametrize('axis', [0, 1, 2])
def test_a_dragged_control_point_travels_along_the_grabbed_axis(axis):
    """The point moves the distance the pointer did, on that axis alone."""
    reported = _drive(axis)
    assert reported['SELECTED'] == str(POINT)
    assert reported['GRABBED'] == str(axis)
    moved = [float(value) for value in reported['MOVED'].split()]
    assert moved[axis] == pytest.approx(DISTANCE, abs=1e-3)
    for other in range(3):
        if other != axis:
            assert moved[other] == pytest.approx(0.0, abs=1e-6)


@gl
def test_the_surface_is_rewritten_where_the_point_landed():
    """The drag is an edit to the geometry, not only to the marker over it."""
    reported = _drive(2)
    landed = [float(value) for value in reported['SURFACE'].split()]
    assert landed == pytest.approx([2.0, 2.0, 6.0 + DISTANCE], abs=1e-3)


@gl
def test_the_release_lets_go_of_the_arm():
    reported = _drive(0)
    assert reported['RELEASED'] == 'True'
