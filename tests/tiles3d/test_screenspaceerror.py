"""Screen-space error: geometric error (world units) -> pixel error for the camera.

The 3D Tiles refinement rule renders a tile when its screen-space error is below a
pixel threshold and refines into children otherwise; these tests pin the standard
perspective SSE relationship so traversal decisions are reproducible.
"""
import math
import pytest

from OpenGLContext.loaders.tiles3d.screenspaceerror import (
    screen_space_error,
    should_refine,
)


FOVY = math.radians(60.0)
VIEWPORT_H = 1080


def test_zero_geometric_error_is_zero_sse():
    # A leaf with no geometric error can never warrant refinement.
    assert screen_space_error(0.0, distance=100.0, viewport_height=VIEWPORT_H, fovy=FOVY) == 0.0


def test_sse_doubles_when_distance_halves():
    far = screen_space_error(10.0, distance=200.0, viewport_height=VIEWPORT_H, fovy=FOVY)
    near = screen_space_error(10.0, distance=100.0, viewport_height=VIEWPORT_H, fovy=FOVY)
    assert near == pytest.approx(2.0 * far, rel=1e-9)


def test_sse_scales_with_viewport_height():
    small = screen_space_error(10.0, distance=100.0, viewport_height=540, fovy=FOVY)
    big = screen_space_error(10.0, distance=100.0, viewport_height=1080, fovy=FOVY)
    assert big == pytest.approx(2.0 * small, rel=1e-9)


def test_distance_at_or_behind_camera_forces_max_detail():
    # Inside/at the bounding volume: infinite error so the tile always refines.
    assert screen_space_error(1.0, distance=0.0, viewport_height=VIEWPORT_H, fovy=FOVY) == math.inf
    assert screen_space_error(1.0, distance=-5.0, viewport_height=VIEWPORT_H, fovy=FOVY) == math.inf


def test_matches_reference_perspective_formula():
    ge, dist = 7.5, 250.0
    expected = (ge * VIEWPORT_H) / (dist * 2.0 * math.tan(0.5 * FOVY))
    assert screen_space_error(ge, dist, VIEWPORT_H, FOVY) == pytest.approx(expected, rel=1e-12)


def test_should_refine_compares_against_pixel_threshold():
    # sse strictly above the max pixel error -> refine; at or below -> render this tile.
    assert should_refine(sse=17.0, max_sse=16.0) is True
    assert should_refine(sse=16.0, max_sse=16.0) is False
    assert should_refine(sse=4.0, max_sse=16.0) is False


def test_should_refine_true_for_infinite_sse():
    assert should_refine(sse=math.inf, max_sse=16.0) is True
