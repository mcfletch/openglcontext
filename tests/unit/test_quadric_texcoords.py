"""Sphere, Cylinder and Cone texture coordinates, as VRML97 and X3D give them.

The sides (and the whole sphere) wrap anticlockwise seen from above from a
seam at the back, -Z: u is 0 there, 0.25 at -X, 0.5 at +Z and 0.75 at +X; v
runs from 0 at the bottom to 1 at the top. A cylinder's top cap shows its
texture upright with the image's top toward -Z, and the bottom caps with the
image's top toward +Z (19775-1, 13.3.2, 13.3.3, 13.3.6).
"""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph.quadrics import Cone, Sphere

SIDE = [((0, 0, -1), 0.0), ((-1, 0, 0), 0.25), ((0, 0, 1), 0.5), ((1, 0, 0), 0.75)]


def at(coords, point, normal=None):
    """The (u, v) of the vertex at `point`, with `normal` where given"""
    rows = coords
    if normal is not None:
        rows = rows[np.all(np.isclose(rows[:, 5:8], normal, atol=1e-5), axis=1)]
    distance = np.linalg.norm(rows[:, 0:3] - np.asarray(point, 'f'), axis=1)
    found = rows[np.isclose(distance, distance.min(), atol=1e-5)]
    return sorted({tuple(round(float(value), 4) for value in row[3:5]) for row in found})


def wraps(found, u):
    """Whether one of `found` has u, a seam vertex taking 0 or 1"""
    return any(math.isclose(fu % 1.0, u % 1.0, abs_tol=1e-4) for fu, _v in found)


@pytest.mark.parametrize('point, u', SIDE)
def test_the_sphere_wraps_from_the_back(point, u):
    coords, _ = Sphere.sphere()
    found = at(coords, point)
    assert wraps(found, u), found
    assert all(math.isclose(v, 0.5, abs_tol=1e-4) for _u, v in found)


def test_the_spheres_top_is_v_1_and_its_u_stays_in_the_unit_square():
    coords, _ = Sphere.sphere()
    assert all(v == 1.0 for _u, v in at(coords, (0, 1, 0)))
    assert all(v == 0.0 for _u, v in at(coords, (0, -1, 0)))
    assert coords[:, 3].min() >= 0.0 and coords[:, 3].max() <= 1.0


@pytest.mark.parametrize('cylinder', [False, True], ids=['cone', 'cylinder'])
@pytest.mark.parametrize('point, u', SIDE)
def test_the_sides_wrap_from_the_back(cylinder, point, u):
    coords, _ = Cone.cone(top=cylinder, cylinder=cylinder)
    side = coords[np.abs(coords[:, 6]) < 0.99]          # side normals are not vertical
    x, _y, z = point
    found = at(side, (x, -1, z))
    assert wraps(found, u), found
    assert all(v == 0.0 for _u, v in found)
    if cylinder:
        assert all(v == 1.0 for _u, v in at(side, (x, 1, z)))
    assert side[:, 3].min() >= 0.0 and side[:, 3].max() <= 1.0


def test_the_top_cap_is_upright_with_its_top_toward_minus_z():
    coords, _ = Cone.cone(top=True, cylinder=True)
    assert at(coords, (0, 1, -1), (0, 1, 0)) == [(0.5, 1.0)]
    assert at(coords, (1, 1, 0), (0, 1, 0)) == [(1.0, 0.5)]


@pytest.mark.parametrize('cylinder', [False, True], ids=['cone', 'cylinder'])
def test_the_bottom_cap_has_its_top_toward_plus_z(cylinder):
    coords, _ = Cone.cone(top=cylinder, cylinder=cylinder)
    assert at(coords, (0, -1, 1), (0, -1, 0)) == [(0.5, 1.0)]
    assert at(coords, (1, -1, 0), (0, -1, 0)) == [(1.0, 0.5)]
