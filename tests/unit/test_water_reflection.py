"""The arithmetic of a planar water reflection, with no GL.

Which plane the frame's water gives, the matrix that mirrors the world in it,
and the projection whose near plane is that water: the three things the
reflection render is built from, asserted as numbers. Drawing one is
``test_water_reflection_gl.py``.
"""
import types

import numpy as np
import pytest

from OpenGLContext.passes import reflection
from OpenGLContext.scenegraph.water import STILL


def _record(level=0.0, translate=(0.0, 0.0, 0.0), style=STILL, scale=1.0):
    """A draw record for a flat sheet at ``level`` in its own space, placed."""
    positions = np.array([(-5, level, -5), (5, level, -5), (5, level, 5)], 'f')
    geometry = types.SimpleNamespace(positions=positions, wave_style=style)
    node = types.SimpleNamespace(geometry=geometry)
    tmatrix = np.identity(4, 'f') * scale
    tmatrix[3] = (*translate, 1.0)
    return ((False,), None, tmatrix, None, (), node)


def _plain():
    node = types.SimpleNamespace(geometry=types.SimpleNamespace(
        positions=np.zeros((3, 3), 'f')))
    return ((False,), None, np.identity(4, 'f'), None, (), node)


# --- the plane ----------------------------------------------------------------

def test_a_frame_without_water_has_no_plane():
    assert reflection.water_plane([_plain()], eye=(0.0, 5.0, 0.0)) is None


def test_the_plane_is_where_the_sheet_stands_in_the_world():
    point, normal = reflection.water_plane(
        [_plain(), _record(level=0.5, translate=(0.0, 2.0, 0.0))],
        eye=(0.0, 10.0, 0.0))
    assert point[1] == pytest.approx(2.5)
    assert tuple(normal) == pytest.approx((0.0, 1.0, 0.0))


def test_a_scaled_sheet_still_faces_up():
    _point, normal = reflection.water_plane(
        [_record(scale=3.0)], eye=(0.0, 10.0, 0.0))
    assert tuple(normal) == pytest.approx((0.0, 1.0, 0.0))


def test_the_nearest_sheet_is_the_one_reflected():
    point, _normal = reflection.water_plane(
        [_record(translate=(0.0, -4.0, 0.0)), _record(translate=(0.0, 1.0, 0.0))],
        eye=(0.0, 3.0, 0.0))
    assert point[1] == pytest.approx(1.0)


def test_a_camera_under_the_water_sees_no_reflection():
    """It is looking up through the surface, not at a mirror."""
    assert reflection.water_plane([_record()], eye=(0.0, -1.0, 0.0)) is None


# --- the mirror ---------------------------------------------------------------

def test_the_mirror_puts_a_point_as_far_below_as_it_was_above():
    mirror = reflection.mirror_matrix((0.0, 2.0, 0.0), (0.0, 1.0, 0.0))
    moved = np.array([3.0, 5.0, -1.0, 1.0]) @ mirror
    assert tuple(moved[:3]) == pytest.approx((3.0, -1.0, -1.0))


def test_the_mirror_turns_the_world_inside_out():
    """Which is why the winding flips in a reflection."""
    mirror = reflection.mirror_matrix((0.0, 2.0, 0.0), (0.0, 1.0, 0.0))
    assert np.linalg.det(mirror[:3, :3]) == pytest.approx(-1.0)


def test_twice_in_the_mirror_is_where_it_started():
    mirror = reflection.mirror_matrix((1.0, -0.5, 2.0), (0.0, 1.0, 0.0))
    assert np.allclose(mirror @ mirror, np.identity(4))


# --- clipping at the water ----------------------------------------------------

def _perspective(near=0.1, far=100.0, fov=1.0):
    """A row-vector perspective projection, as the engine's matrices are."""
    f = 1.0 / np.tan(fov / 2.0)
    column = np.array([
        [f, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
        [0, 0, -1, 0],
    ], 'd')
    return column.T


def _ndc_depth(projection, point):
    clip = np.append(point, 1.0) @ projection
    return clip[2] / clip[3]


#: Eye space for the mirrored camera, which stands under the water: it looks
#: down -z, and the water is the plane y = 1 above it. What is kept is what is
#: above the water, y >= 1.
WATER = (0.0, 1.0, 0.0, -1.0)


def test_the_oblique_projection_keeps_what_is_above_the_water():
    projection = reflection.oblique_projection(_perspective(), WATER)
    assert -1.0 < _ndc_depth(projection, (0.0, 3.0, -10.0)) < 1.0


def test_and_clips_what_is_between_the_camera_and_the_water():
    """Under the surface, where the lake bed would be mirrored into the sky."""
    projection = reflection.oblique_projection(_perspective(), WATER)
    assert _ndc_depth(projection, (0.0, 0.5, -10.0)) < -1.0


def test_the_view_of_what_is_kept_is_unchanged():
    """Only depth is bent; where a point lands on screen is not."""
    plain = _perspective()
    projection = reflection.oblique_projection(plain, WATER)
    point = np.array([0.7, 4.0, -12.0, 1.0])
    expected = point @ plain
    clip = point @ projection
    assert clip[0] / clip[3] == pytest.approx(expected[0] / expected[3])
    assert clip[1] / clip[3] == pytest.approx(expected[1] / expected[3])


def test_the_eye_space_plane_follows_the_view():
    """The world plane y = 2, seen by a camera standing at y = 5."""
    view = np.identity(4)
    view[3] = (0.0, -5.0, 0.0, 1.0)
    plane = reflection.eye_plane((0.0, 2.0, 0.0), (0.0, 1.0, 0.0), view)
    above = np.array([0.0, 3.0, -4.0, 1.0]) @ view
    below = np.array([0.0, 1.0, -4.0, 1.0]) @ view
    assert float(np.dot(plane, above)) > 0.0
    assert float(np.dot(plane, below)) < 0.0


# --- the plan for one view ----------------------------------------------------

def _view(eye=(0.0, 5.0, 10.0)):
    """A camera standing at ``eye`` looking down -z, as a row-vector view."""
    view = np.identity(4)
    view[3, :3] = -np.asarray(eye, dtype='d')
    return view


def test_a_view_with_no_water_plans_nothing():
    assert reflection.plan([_plain()], _view(), _perspective(), (0, 0, 200, 100)) is None


def test_the_plan_mirrors_the_camera_in_the_water():
    """A point seen through the mirrored camera is its reflection seen through the real one."""
    planned = reflection.plan([_record(translate=(0.0, 1.0, 0.0))], _view(),
                              _perspective(), (0, 0, 200, 100))
    point = np.array([2.0, 4.0, -3.0, 1.0])
    reflected = np.array([2.0, -2.0, -3.0, 1.0])
    assert np.allclose(point @ planned.modelView, reflected @ _view())


def test_the_plan_clips_below_the_water():
    planned = reflection.plan([_record(translate=(0.0, 1.0, 0.0))], _view(),
                              _perspective(), (0, 0, 200, 100))
    above = np.array([0.0, 3.0, -20.0, 1.0]) @ planned.modelView @ planned.projection
    below = np.array([0.0, 0.5, -20.0, 1.0]) @ planned.modelView @ planned.projection
    assert -1.0 < above[2] / above[3] < 1.0
    assert below[2] / below[3] < -1.0


def test_the_target_is_half_the_view_each_way():
    planned = reflection.plan([_record()], _view(), _perspective(), (40, 20, 200, 100))
    assert planned.size == (100, 50)
