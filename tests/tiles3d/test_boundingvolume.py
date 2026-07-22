"""Bounding-volume distance used to drive screen-space error.

Traversal needs the distance from the camera to the nearest point of a tile's
bounding volume (0 when the camera is inside). These tests pin sphere and oriented
box behaviour, including a rotated box, so SSE distances are correct.
"""
import math
import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d.boundingvolume import (
    SphereBV, BoxBV, RegionBV, geodetic_to_ecef, WGS84_A,
)


def test_sphere_distance_outside():
    s = SphereBV(center=(0, 0, 0), radius=2.0)
    assert s.distance_to((5, 0, 0)) == pytest.approx(3.0)


def test_sphere_distance_inside_is_zero():
    s = SphereBV(center=(1, 1, 1), radius=5.0)
    assert s.distance_to((2, 1, 1)) == 0.0


def test_sphere_center():
    s = SphereBV(center=(1, 2, 3), radius=1.0)
    assert tuple(s.center) == (1.0, 2.0, 3.0)


def _axis_box():
    # Axis-aligned OBB: half-extents 2,3,4 along x,y,z.
    return BoxBV(center=(0, 0, 0), half_axes=[(2, 0, 0), (0, 3, 0), (0, 0, 4)])


def test_box_distance_along_one_axis():
    assert _axis_box().distance_to((5, 0, 0)) == pytest.approx(3.0)


def test_box_distance_is_zero_inside():
    assert _axis_box().distance_to((1, -2, 3)) == 0.0


def test_box_distance_diagonal_uses_euclidean_excess():
    # excess x = 5-2 = 3, excess y = 7-3 = 4 -> 5
    assert _axis_box().distance_to((5, 7, 0)) == pytest.approx(5.0)


def test_box_center():
    assert tuple(_axis_box().center) == (0.0, 0.0, 0.0)


def test_rotated_box_distance():
    # Box local-x points along world +y with half-extent 2; local-y along world -x
    # half-extent 3; local-z world +z half-extent 1. A point 5 along world +y is
    # 5 from center projected onto local-x (half 2) -> excess 3.
    b = BoxBV(center=(0, 0, 0), half_axes=[(0, 2, 0), (-3, 0, 0), (0, 0, 1)])
    assert b.distance_to((0, 5, 0)) == pytest.approx(3.0)
    assert b.distance_to((0, 1.5, 0)) == 0.0


# -- geodetic region volumes ------------------------------------------------

def test_geodetic_origin_maps_to_equator_prime_meridian():
    # lon=0, lat=0, h=0 sits on the +X axis at the semi-major radius.
    x, y, z = geodetic_to_ecef(0.0, 0.0, 0.0)
    assert x == pytest.approx(WGS84_A)
    assert y == pytest.approx(0.0, abs=1e-6)
    assert z == pytest.approx(0.0, abs=1e-6)


def test_geodetic_height_extends_radially_at_equator():
    x, _, _ = geodetic_to_ecef(0.0, 0.0, 1000.0)
    assert x == pytest.approx(WGS84_A + 1000.0)


def test_geodetic_north_pole_on_z_axis():
    x, y, z = geodetic_to_ecef(0.0, math.pi / 2, 0.0)
    assert x == pytest.approx(0.0, abs=1e-6)
    assert y == pytest.approx(0.0, abs=1e-6)
    assert z > 6.35e6  # semi-minor axis, ~6356 km


def _small_region():
    # ~0.001 rad (~6 km) box straddling the equator/prime meridian, 0..100 m.
    d = 5e-4
    return RegionBV([-d, -d, d, d, 0.0, 100.0])


def test_region_sphere_sits_on_ellipsoid():
    c, r = _small_region().bounding_sphere()
    # Centre is ~one Earth radius from the geocentre, near the +X axis.
    assert np.linalg.norm(c) == pytest.approx(WGS84_A, rel=1e-4)
    assert r < 1.0e4  # a few-km patch, not the whole globe


def test_region_distance_zero_inside_positive_outside():
    bv = _small_region()
    c, r = bv.bounding_sphere()
    assert bv.distance_to(c) == 0.0
    far = c + (c / np.linalg.norm(c)) * (r + 500.0)
    assert bv.distance_to(far) == pytest.approx(500.0, rel=1e-3)


def test_region_recenter_offset_brings_patch_to_origin():
    bv = _small_region()
    c, _ = bv.bounding_sphere()
    recentred = RegionBV([-5e-4, -5e-4, 5e-4, 5e-4, 0.0, 100.0], offset=c)
    c2, _ = recentred.bounding_sphere()
    assert np.linalg.norm(c2) < 1.0e4  # now near the origin, not 6400 km out
