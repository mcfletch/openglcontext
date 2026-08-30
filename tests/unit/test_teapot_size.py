"""Teapot.size scales the pot itself, in both the colour and the depth pass.

The size is folded into the modelview rather than baked into the cached mesh, so
the composition order is what decides whether it scales the pot or the space the
pot is drawn in. Scaling eye space is invisible under a perspective projection --
the divide by w cancels it -- so a wrong order shows up not as a pot of the wrong
size but as a pot whose depth is wrong, which the shadow map then reads as an
occluder standing somewhere the pot is not.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.teapot import Teapot


class _Recorder:
    """Stands in for VRML97ShaderProgram, keeping the matrices it is handed."""

    def __init__(self):
        self.matrices = []

    def set_matrices(self, modelview, projection, program=None):
        self.matrices.append(np.asarray(modelview, dtype='d'))


class _Mode:
    """The two attributes _with_scaled_matrix reads off a rendering pass."""

    def __init__(self, matrix):
        self.matrix = np.asarray(matrix, dtype='f')
        self.projection = np.identity(4, dtype='f')


def _camera_back(distance):
    """Row-vector modelview for a camera ``distance`` units along +z."""
    view = np.identity(4, dtype='f')
    view[3, :3] = (0, 0, -distance)
    return view


def _drawn_matrix(size, view):
    recorder = _Recorder()
    Teapot(size=size)._with_scaled_matrix(_Mode(view), recorder, lambda: None)
    return recorder.matrices[0] if recorder.matrices else np.asarray(view, dtype='d')


@pytest.mark.parametrize('size', [0.25, 0.5, 2.0])
def test_size_scales_the_pot_and_not_the_view(size):
    """A model point lands at ``size`` times its own coordinates, at view depth."""
    view = _camera_back(6.0)
    point = np.dot(np.array([1.0, 2.0, 3.0, 1.0]), _drawn_matrix(size, view))
    assert np.allclose(point[:3], (size * 1.0, size * 2.0, size * 3.0 - 6.0))


def test_unit_size_leaves_the_matrix_alone():
    """size 1.0 needs no scale, so the pass's own matrix is what is drawn with."""
    view = _camera_back(6.0)
    assert np.allclose(_drawn_matrix(1.0, view), view)


def test_size_reaches_the_depth_a_shadow_map_records():
    """Two sizes put the pot's surface at two different depths from the camera.

    The eye-space z is what a depth map stores. Were the scale applied to eye
    space rather than to the pot, both sizes would report the same depth and a
    shadow map would place a size-0.5 pot where a size-1 pot stands.
    """
    view = _camera_back(6.0)
    spout = np.array([0.0, 0.0, 1.0, 1.0])
    small = np.dot(spout, _drawn_matrix(0.5, view))
    large = np.dot(spout, _drawn_matrix(1.0, view))
    assert small[2] != pytest.approx(large[2])
    assert small[2] == pytest.approx(-6.0 + 0.5)
    assert large[2] == pytest.approx(-6.0 + 1.0)
