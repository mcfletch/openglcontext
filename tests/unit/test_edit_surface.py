"""Finding the point under the cursor, and dragging it about.

An editor's first question is "where on the world did they click?", and its
second is "where are they dragging it to?". The first is answered by the depth
the pick already reads back; the second by arithmetic against a plane, because
once something is being dragged the depth under the cursor is the thing being
dragged and no longer says where it is going.

Headless: unprojection is matrix arithmetic and a ray meeting a plane is a
division.
"""
import math

import numpy as np
import pytest

from OpenGLContext.events.mouseevents import MouseEvent
from OpenGLContext.edit.surface import (
    horizon_plane, pointer_from, ray_from, ray_plane, surface_normal,
)


FIELD_OF_VIEW = math.radians(60.0)


def _matrices(eye=(0.0, 10.0, 20.0), target=(0.0, 0.0, 0.0),
              viewport=(0, 0, 800, 600), fov=FIELD_OF_VIEW):
    """A camera looking at a target, as the row-vector matrices an event has."""
    forward = np.asarray(target, 'd') - np.asarray(eye, 'd')
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, (0.0, 1.0, 0.0))
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    view = np.identity(4)
    view[:3, 0] = right
    view[:3, 1] = up
    view[:3, 2] = -forward
    view[3, :3] = -np.array([np.dot(eye, right), np.dot(eye, up),
                             np.dot(eye, -forward)])
    aspect = viewport[2] / viewport[3]
    f = 1.0 / math.tan(fov / 2.0)
    near, far = 0.5, 500.0
    projection = np.zeros((4, 4))
    projection[0, 0] = f / aspect
    projection[1, 1] = f
    projection[2, 2] = (far + near) / (near - far)
    projection[2, 3] = -1.0
    projection[3, 2] = 2 * far * near / (near - far)
    return view, projection, viewport


class _Event(MouseEvent):
    """A real mouse event with a camera on it, so the unprojection is the
    engine's own rather than a second copy of it written for the test."""

    def __init__(self, x, y, depth=None, button=0, modifiers=(0, 0, 0)):
        view, projection, viewport = _matrices()
        self.modelViewMatrix = view
        self.projectionMatrix = projection
        self.viewport = viewport
        self.pickPoint = (x, y)
        self.viewCoordinate = () if depth is None else (x, y, depth)
        self.worldCoordinate = ()
        self.button = button
        self._modifiers = modifiers

    def getModifiers(self):
        return self._modifiers


def _flat(x, z):
    return np.zeros_like(np.asarray(x, 'd'))


def _slope(x, z):
    """Ground that climbs one in four towards +x."""
    return 0.25 * np.asarray(x, 'd')


class TestARayMeetingAPlane:
    def test_straight_down_onto_the_ground(self) -> None:
        hit = ray_plane((0.0, 10.0, 0.0), (0.0, -1.0, 0.0),
                        (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        assert np.allclose(hit, (0.0, 0.0, 0.0))

    def test_at_an_angle(self) -> None:
        hit = ray_plane((0.0, 10.0, 0.0), (1.0, -1.0, 0.0),
                        (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        assert np.allclose(hit, (10.0, 0.0, 0.0))

    def test_a_plane_at_a_height(self) -> None:
        hit = ray_plane((0.0, 10.0, 0.0), (0.0, -1.0, 0.0),
                        (0.0, 4.0, 0.0), (0.0, 1.0, 0.0))
        assert np.allclose(hit, (0.0, 4.0, 0.0))

    def test_a_ray_along_the_plane_never_meets_it(self) -> None:
        assert ray_plane((0.0, 10.0, 0.0), (1.0, 0.0, 0.0),
                         (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)) is None

    def test_a_ray_pointing_away_never_meets_it(self) -> None:
        """Behind the eye is not in front of it."""
        assert ray_plane((0.0, 10.0, 0.0), (0.0, 1.0, 0.0),
                         (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)) is None

    def test_the_horizon_plane_is_level_at_a_height(self) -> None:
        point, normal = horizon_plane(7.0)
        assert tuple(point) == (0.0, 7.0, 0.0)
        assert tuple(normal) == (0.0, 1.0, 0.0)


class TestTheRayThroughTheCursor:
    def test_it_starts_at_the_near_plane(self) -> None:
        """Not at the eye: an orthographic map view has no eye for the rays to
        come from, and its rays are parallel. The near plane is where a ray
        starts under any projection."""
        eye = np.array([0.0, 10.0, 20.0])
        origin, direction = ray_from(_Event(400, 300))
        assert np.allclose(origin, eye + direction * 0.5, atol=1e-3)

    def test_the_centre_of_the_screen_looks_at_what_the_camera_does(self) -> None:
        _origin, direction = ray_from(_Event(400, 300))
        expected = np.array([0.0, -10.0, -20.0])
        expected = expected / np.linalg.norm(expected)
        assert np.allclose(direction, expected, atol=1e-3)

    def test_it_is_a_unit_vector(self) -> None:
        _origin, direction = ray_from(_Event(700, 100))
        assert float(np.linalg.norm(direction)) == pytest.approx(1.0)

    def test_the_right_of_the_screen_looks_right(self) -> None:
        _origin, centre = ray_from(_Event(400, 300))
        _origin, right = ray_from(_Event(700, 300))
        assert right[0] > centre[0]

    def test_it_meets_the_ground_where_the_camera_is_pointed(self) -> None:
        origin, direction = ray_from(_Event(400, 300))
        hit = ray_plane(origin, direction, *horizon_plane(0.0))
        assert np.allclose(hit, (0.0, 0.0, 0.0), atol=1e-2)


class TestThePointerAnEventGives:
    def test_it_carries_the_screen_position(self) -> None:
        pointer = pointer_from(_Event(120, 340))
        assert (pointer.x, pointer.y) == (120, 340)

    def test_a_depth_becomes_a_point_in_the_world(self) -> None:
        """What the pick read back is where the surface is."""
        pointer = pointer_from(_Event(400, 300, depth=0.5))
        assert pointer.on_surface
        # Straight down the view axis, so it is somewhere on that line.
        assert abs(float(pointer.world[0])) < 1e-3

    def test_over_the_sky_there_is_no_point(self) -> None:
        """Nothing was drawn there, so the depth is the far plane and there is
        no surface to speak of."""
        assert not pointer_from(_Event(400, 300, depth=1.0)).on_surface

    def test_with_no_depth_at_all_there_is_no_point(self) -> None:
        assert not pointer_from(_Event(400, 300)).on_surface

    def test_it_carries_the_button_and_the_modifiers(self) -> None:
        pointer = pointer_from(_Event(10, 10, button=2, modifiers=(1, 0, 0)))
        assert pointer.button == 2 and pointer.shifted

    def test_what_was_picked_can_be_passed_along(self) -> None:
        marker = object()
        assert pointer_from(_Event(10, 10), node=marker).node is marker


class TestTheGroundsNormal:
    def test_level_ground_points_straight_up(self) -> None:
        assert np.allclose(surface_normal(_flat, 3.0, -2.0), (0, 1, 0))

    def test_it_is_a_unit_vector(self) -> None:
        normal = surface_normal(_slope, 3.0, -2.0)
        assert float(np.linalg.norm(normal)) == pytest.approx(1.0)

    def test_a_slope_leans_away_from_the_climb(self) -> None:
        """Ground rising towards +x has a normal leaning towards -x."""
        normal = surface_normal(_slope, 0.0, 0.0)
        assert normal[0] < 0.0 and normal[1] > 0.0

    def test_the_lean_matches_the_gradient(self) -> None:
        normal = surface_normal(_slope, 0.0, 0.0)
        assert float(normal[0] / normal[1]) == pytest.approx(-0.25, abs=1e-3)

    def test_it_answers_arrays_as_well_as_points(self) -> None:
        x = np.array([0.0, 4.0, 8.0])
        z = np.zeros(3)
        normals = surface_normal(_slope, x, z)
        assert normals.shape == (3, 3)
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
