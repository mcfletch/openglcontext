"""A mouse event's window coordinates and world coordinates, each from the other.

``MouseEvent.unproject`` turns a window position and depth into the world
point under the pointer, and ``MouseEvent.project`` goes the other way, both
through the matrices and viewport of the frame the event was picked in.  They
are arithmetic on those three, and work where the GLU library is not
installed.
"""
import math
import subprocess
import sys

import numpy as np
import pytest
from vrml.vrml97 import transformmatrix

from OpenGLContext.events.mouseevents import MouseEvent, projected, unprojected


def _event():
    """A camera 10 back from the origin, a 60 degree lens, a 200 x 100 viewport."""
    event = MouseEvent()
    model = np.identity(4)
    model[3, :3] = (0.0, 0.0, -10.0)
    event.modelViewMatrix = model.astype('f')
    event.projectionMatrix = transformmatrix.perspectiveMatrix(
        math.radians(60.0), 2.0, 1.0, 100.0)
    event.viewport = (0, 0, 200, 100)
    return event


def test_the_middle_of_the_window_unprojects_onto_the_line_of_sight():
    x, y, z = _event().unproject((100.0, 50.0, 0.5))
    assert (x, y) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert -10.0 < z < 9.0


def test_the_near_plane_is_depth_zero():
    assert _event().unproject((100.0, 50.0, 0.0)) == pytest.approx((0.0, 0.0, 9.0), abs=1e-5)


def test_a_point_projects_back_to_where_it_came_from():
    event = _event()
    world = event.unproject((37.0, 81.0, 0.8))
    assert event.project(world) == pytest.approx((37.0, 81.0, 0.8), abs=1e-4)


def test_the_answers_are_tuples_of_floats():
    """Callers test them for truth, as the GLU functions' answers were."""
    event = _event()
    world = event.unproject((10.0, 20.0, 0.3))
    assert isinstance(world, tuple) and all(type(c) is float for c in world)
    window = event.project((1.0, 2.0, 3.0))
    assert isinstance(window, tuple) and all(type(c) is float for c in window)


def test_an_event_keeps_the_world_point_of_its_own_view_coordinate():
    event = _event()
    event.viewCoordinate = (100.0, 50.0, 0.0)
    assert event.unproject() == pytest.approx((0.0, 0.0, 9.0), abs=1e-5)
    assert event.worldCoordinate == event.unproject()


def test_a_raw_depth_buffer_value_is_scaled_to_the_unit_range():
    event = _event()
    assert event.unproject((100.0, 50.0, 0)) == pytest.approx(
        event.unproject((100.0, 50.0, 0.0)))


def test_the_functions_take_any_view_with_the_three_attributes():
    event = _event()
    assert tuple(unprojected(event, 37.0, 81.0, 0.8)) == pytest.approx(
        event.unproject((37.0, 81.0, 0.8)))
    assert tuple(projected(event, (1.0, 2.0, 3.0))) == pytest.approx(
        event.project((1.0, 2.0, 3.0)))


def test_it_agrees_with_glu_where_glu_is_installed():
    from OpenGL.GLU import gluProject, gluUnProject
    if not bool(gluUnProject):
        pytest.skip('the GLU library is not installed here')
    event = _event()
    model = event.modelViewMatrix.astype('d')
    projection = np.asarray(event.projectionMatrix, 'd')
    viewport = np.array(event.viewport, 'i')
    assert event.unproject((37.0, 81.0, 0.8)) == pytest.approx(
        tuple(gluUnProject(37.0, 81.0, 0.8, model, projection, viewport)), abs=1e-5)
    assert event.project((1.0, 2.0, 3.0)) == pytest.approx(
        tuple(gluProject(1.0, 2.0, 3.0, model, projection, viewport)), abs=1e-4)


def test_it_projects_where_glu_is_not_installed():
    script = '\n'.join([
        'from OpenGL import platform',
        'platform.PLATFORM.GLU = None',
        'import numpy as np',
        'from OpenGLContext.events.mouseevents import MouseEvent',
        'event = MouseEvent()',
        'event.modelViewMatrix = np.identity(4, "f")',
        'event.projectionMatrix = np.identity(4, "f")',
        'event.viewport = (0, 0, 100, 100)',
        'print(event.project(event.unproject((25.0, 75.0, 0.5))))',
    ])
    done = subprocess.run([sys.executable, '-c', script],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == '(25.0, 75.0, 0.5)'
