"""View-frustum culling: matrices and sphere tests used to limit the working set.

Frustum culling is what turns the tileset into a *moving window* around the view — it
is what lets streaming hold a small resident set instead of the whole world. These
tests pin the perspective/look-at matrices and the sphere-in-frustum classification.
"""
import math

import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d.frustum import (
    perspective, look_at, view_projection, Frustum,
)


def _vp(eye, center):
    return view_projection(eye, center, up=(0, 1, 0),
                           fovy=math.radians(60), aspect=1.0, near=1.0, far=5000.0)


def test_point_ahead_is_inside():
    f = Frustum.from_matrix(_vp((0, 0, 0), (0, 0, -1)))
    assert f.contains_sphere(np.array([0.0, 0.0, -100.0]), 1.0)


def test_point_behind_is_outside():
    f = Frustum.from_matrix(_vp((0, 0, 0), (0, 0, -1)))
    assert not f.contains_sphere(np.array([0.0, 0.0, 100.0]), 1.0)


def test_far_off_axis_is_outside():
    f = Frustum.from_matrix(_vp((0, 0, 0), (0, 0, -1)))
    assert not f.contains_sphere(np.array([5000.0, 0.0, -100.0]), 1.0)


def test_big_sphere_straddling_plane_is_inside():
    # A sphere centred just behind the camera but large enough to poke into view.
    f = Frustum.from_matrix(_vp((0, 0, 0), (0, 0, -1)))
    assert f.contains_sphere(np.array([0.0, 0.0, 20.0]), 60.0)


def test_looking_the_other_way_flips_visibility():
    ahead = np.array([0.0, 0.0, -100.0])
    f_fwd = Frustum.from_matrix(_vp((0, 0, 0), (0, 0, -1)))
    f_back = Frustum.from_matrix(_vp((0, 0, 0), (0, 0, 1)))
    assert f_fwd.contains_sphere(ahead, 1.0)
    assert not f_back.contains_sphere(ahead, 1.0)


def test_looking_straight_down_along_up_gives_a_rotation():
    """A camera looking along its own up has no right from them; one is chosen."""
    m = look_at((0.0, 100.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    rotation = m[:3, :3]
    assert np.allclose(rotation @ rotation.T, np.eye(3))
    assert np.allclose(rotation[2], (0.0, 1.0, 0.0))      # the view is along -y
    assert np.allclose(m @ (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, -100.0, 1.0))


def test_looking_straight_up_gives_a_rotation():
    m = look_at((0.0, 0.0, 0.0), (0.0, 5.0, 0.0), (0.0, 1.0, 0.0))
    assert np.allclose(m[:3, :3] @ m[:3, :3].T, np.eye(3))


def test_an_eye_at_the_point_looked_at_is_refused():
    with pytest.raises(ValueError):
        look_at((1.0, 2.0, 3.0), (1.0, 2.0, 3.0), (0.0, 1.0, 0.0))
