"""A shadow's depth bias is a count of texels, whatever map it lands in.

The receiver compares its own depth against the map's and needs a nudge toward
the light to stop a surface shadowing itself. What that nudge has to clear is the
map's quantisation -- the caster was sampled at texel centres -- so the scale it
belongs on is the texel, not the metre and certainly not the map's own depth
units. Depth is 1/z in a spot or cube map and linear in a cascade, and a texel
covers a fixed width in a cascade and a growing one in the others, so a bias
fixed in depth is a different slack in every map and at every depth inside a
perspective one: enough to detach a shadow from the object casting it under one
light and not enough to clear acne under the next.

:func:`~OpenGLContext.passes.shadowmath.depth_bias_terms` is the conversion.
"""
import numpy as np
import pytest

from OpenGLContext.passes import shadowmath

RESOLUTION = 2048
FOV = 0.6            # spot half-angle; the projection uses the full cone


def _perspective(near, far):
    return shadowmath.spot_light_view_projection(
        (0, 0, 0), (0, 0, -1), FOV, near, far)[1]


def _ortho(near, far, half=10.0):
    return shadowmath.ortho_matrix(-half, half, -half, half, near, far)


def _window_depth(projection, distance):
    """Window depth (0..1) a point ``distance`` along the light's view axis lands at."""
    eye = np.array([0.0, 0.0, -float(distance), 1.0])
    clip = np.dot(eye, np.asarray(projection, dtype='d'))
    return float(clip[2] / clip[3]) * 0.5 + 0.5


def _applied(terms, depth):
    """What the shader computes from the terms: scale*(reference - d) + constant."""
    scale, reference, constant = terms
    return scale * (reference - depth) + constant


def _distance_at(projection, depth):
    """Distance along the view axis whose window depth is ``depth``."""
    p = np.asarray(projection, dtype='d')
    if p[2][3] == 0:                      # orthographic: depth is linear
        span = -2.0 / p[2][2]
        near = -(p[3][2] * span + span) * 0.5
        return near + depth * span
    c, d = p[2][2], p[3][2]
    near, far = d / (c - 1.0), d / (c + 1.0)
    return far * near / (far - depth * (far - near))


def _texel_width(projection, distance):
    """World width of one shadow texel at ``distance`` along the view axis."""
    p = np.asarray(projection, dtype='d')
    per_unit = 2.0 / (p[0][0] * RESOLUTION)
    return per_unit * distance if p[2][3] else per_unit


@pytest.mark.parametrize('distance', [2.0, 8.0, 25.0, 45.0])
def test_a_perspective_bias_is_the_same_count_of_texels_at_every_depth(distance):
    """Two texels of slack stays two texels of slack from near plane to far.

    A spot map's texels fan out with distance and its depth crowds toward the far
    plane; converting through both is what keeps the number the light asked for
    meaningful across its whole cone.
    """
    projection = _perspective(0.5, 50.0)
    terms = shadowmath.depth_bias_terms(projection, 2.0, RESOLUTION)

    depth = _window_depth(projection, distance)
    moved = distance - _distance_at(projection, depth - _applied(terms, depth))
    assert moved == pytest.approx(2.0 * _texel_width(projection, distance), rel=0.05)


def test_the_bias_does_not_change_with_the_scale_of_the_scene():
    """A room and a landscape lit the same way get the same offset.

    Every distance in the light's setup is multiplied by a hundred. Texels grow
    with it and depth resolution shifts with it, and the two cancel: the shader
    subtracts the same number in both.
    """
    small = shadowmath.depth_bias_terms(_perspective(0.5, 50.0), 1.0, RESOLUTION)
    large = shadowmath.depth_bias_terms(_perspective(50.0, 5000.0), 1.0, RESOLUTION)
    for depth in (0.2, 0.6, 0.95):
        assert _applied(small, depth) == pytest.approx(_applied(large, depth))

    small_o = shadowmath.depth_bias_terms(_ortho(1.0, 41.0, half=10.0), 1.0, RESOLUTION)
    large_o = shadowmath.depth_bias_terms(_ortho(100.0, 4100.0, half=1000.0), 1.0, RESOLUTION)
    assert _applied(small_o, 0.5) == pytest.approx(_applied(large_o, 0.5))


def test_a_finer_map_needs_a_smaller_offset():
    """Twice the resolution is half the texel, so half the depth to clear."""
    projection = _perspective(0.5, 50.0)
    coarse = shadowmath.depth_bias_terms(projection, 1.0, 1024)
    fine = shadowmath.depth_bias_terms(projection, 1.0, 2048)
    assert _applied(fine, 0.7) == pytest.approx(_applied(coarse, 0.7) * 0.5)


def test_an_orthographic_bias_is_flat_across_the_cascade():
    """A cascade's texels and depth are both linear, so one offset serves it."""
    near, far, half = 1.0, 41.0, 10.0
    terms = shadowmath.depth_bias_terms(_ortho(near, far, half), 3.0, RESOLUTION)
    expected = 3.0 * (2.0 * half / RESOLUTION) / (far - near)
    assert _applied(terms, 0.1) == pytest.approx(expected)
    assert _applied(terms, 0.9) == pytest.approx(expected)


def test_zero_bias_asks_for_no_offset():
    """A light with the bias turned off compares depths as they are."""
    terms = shadowmath.depth_bias_terms(_perspective(0.5, 50.0), 0.0, RESOLUTION)
    assert _applied(terms, 0.3) == pytest.approx(0.0)


def test_a_degenerate_map_yields_a_usable_number():
    """A collapsed range or width must not put a NaN or an infinity in a uniform."""
    collapsed = np.identity(4, dtype='f')
    collapsed[2][2], collapsed[2][3], collapsed[3][2] = -1.0, -1.0, 0.0
    flat = np.zeros((4, 4), dtype='f')
    for projection in (collapsed, flat, _ortho(2.0, 2.0)):
        terms = shadowmath.depth_bias_terms(projection, 1.0, RESOLUTION)
        assert np.all(np.isfinite(np.asarray(terms, dtype='d')))
