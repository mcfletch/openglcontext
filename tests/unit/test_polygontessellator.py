"""The triangle sets PolygonTessellator makes from contours of vertices.

Every triangle winds counter-clockwise about the polygon's normal, the given
one or the one the contours define, so a caller drawing the result with face
culling on sees every triangle.  The vertices out are the vertices in, plus a
blended vertex where two edges cross; and none of it needs a GL context or the
GLU library.
"""

import math
import subprocess
import sys

import pytest
from OpenGL.GL import GL_TRIANGLES
from OpenGL.raw.GLU.constants import GLU_TESS_WINDING_NONZERO

from OpenGLContext.scenegraph import polygontessellator
from OpenGLContext.scenegraph.vertex import Vertex


def _circle(radius, direction, steps=16):
    return [
        Vertex(point=(
            math.cos(direction * i * 2 * math.pi / steps) * radius,
            math.sin(direction * i * 2 * math.pi / steps) * radius,
            0.0,
        ))
        for i in range(steps)
    ]


def _ring(outer=2.0, inner=1.0):
    """An annulus: outer contour counter-clockwise, hole clockwise, like an 'O'."""
    return [_circle(outer, 1), _circle(inner, -1)]


def _square(x, y, size=1.0, z=0.0):
    return [Vertex(point=p) for p in (
        (x, y, z), (x + size, y, z), (x + size, y + size, z), (x, y + size, z))]


def _triangles(vertices):
    assert len(vertices) % 3 == 0
    return [vertices[i:i + 3] for i in range(0, len(vertices), 3)]


def _signed_area(triangle):
    """Twice the signed area in the xy-plane: positive when counter-clockwise."""
    (ax, ay, _), (bx, by, _), (cx, cy, _) = [v.point for v in triangle]
    return (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)


def _area(vertices):
    return sum(abs(_signed_area(t)) for t in _triangles(vertices)) / 2.0


def _polygon_area(radius, steps=16):
    return 0.5 * steps * radius * radius * math.sin(2 * math.pi / steps)


@pytest.fixture
def tessellator():
    return polygontessellator.PolygonTessellator()


def test_a_ring_winds_counter_clockwise_about_the_normal_given(tessellator):
    triangles = _triangles(tessellator.tessContours(_ring(), normal=(0, 0, 1)))
    backwards = [t for t in triangles if _signed_area(t) < 0]
    assert not backwards, '%d of %d triangles wind clockwise' % (
        len(backwards), len(triangles))


def test_the_opposite_normal_winds_every_triangle_the_other_way(tessellator):
    triangles = _triangles(tessellator.tessContours(_ring(), normal=(0, 0, -1)))
    assert triangles
    assert all(_signed_area(t) < 0 for t in triangles)


def test_a_ring_covers_its_area_and_not_its_hole(tessellator):
    vertices = tessellator.tessContours(_ring())
    assert _area(vertices) == pytest.approx(_polygon_area(2.0) - _polygon_area(1.0))
    for triangle in _triangles(vertices):
        x, y = (sum(v.point[i] for v in triangle) / 3.0 for i in (0, 1))
        assert math.hypot(x, y) > 0.9


def test_the_vertices_out_are_the_vertices_given(tessellator):
    """No crossing, so nothing is invented and per-vertex data rides along."""
    contours = _ring()
    given = {id(v) for contour in contours for v in contour}
    vertices = tessellator.tessContours(contours)
    assert {id(v) for v in vertices} == given


def test_with_no_normal_a_face_winds_as_it_was_given(tessellator):
    """The normal the contour defines, as for an IndexedFaceSet's face."""
    clockwise = _circle(1.0, -1, steps=7)
    triangles = _triangles(tessellator.tessellate(clockwise))
    assert len(triangles) == 5
    assert all(_signed_area(t) < 0 for t in triangles)


def test_a_convex_face_is_a_fan_of_its_own_vertices(tessellator):
    hexagon = _circle(1.0, 1, steps=6)
    vertices = tessellator.tessellate(hexagon)
    assert [hexagon.index(v) for v in vertices] == [
        0, 1, 2, 0, 2, 3, 0, 3, 4, 0, 4, 5]


def test_a_concave_face_covers_its_area(tessellator):
    ell = [Vertex(point=p) for p in (
        (0, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0))]
    triangles = _triangles(tessellator.tessellate(ell))
    assert len(triangles) == 4
    assert all(_signed_area(t) > 0 for t in triangles)
    assert _area(tessellator.tessellate(ell)) == pytest.approx(3.0)


def test_a_pentagram_is_not_taken_for_convex(tessellator):
    """Every turn is the same way, but the outline goes round twice: under the
    odd rule the middle, wound twice, is empty."""
    pentagram = [_circle(1.0, 1, steps=5)[(i * 2) % 5] for i in range(5)]
    whole = _area(tessellator.tessellate(_circle(1.0, 1, steps=5)))
    points = _area(tessellator.tessellate(pentagram))
    assert 0 < points < whole * 0.75


def test_a_face_with_a_straight_run_covers_its_area(tessellator):
    """A vertex in the middle of an edge turns neither way."""
    square = [Vertex(point=p) for p in (
        (0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0))]
    assert _area(tessellator.tessellate(square)) == pytest.approx(4.0)


def test_a_face_off_the_axes_is_triangulated_in_its_own_plane(tessellator):
    """A hexagon in the plane x + y + z = 1, not projected flat onto z=0."""
    centre, normal = (1 / 3.0,) * 3, (1, 1, 1)
    u = (1 / math.sqrt(2), -1 / math.sqrt(2), 0.0)
    v = (1 / math.sqrt(6), 1 / math.sqrt(6), -2 / math.sqrt(6))
    hexagon = [
        Vertex(point=tuple(
            centre[k] + math.cos(a) * u[k] + math.sin(a) * v[k] for k in range(3)))
        for a in (i * math.pi / 3 for i in range(6))
    ]
    vertices = tessellator.tessellate(hexagon)
    assert len(vertices) == 12
    for triangle in _triangles(vertices):
        a, b, c = (t.point for t in triangle)
        ab, ac = b - a, c - a
        cross = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2],
                 ab[0] * ac[1] - ab[1] * ac[0])
        facing = sum(cross[k] * normal[k] for k in range(3))
        assert facing != 0


def test_clockwise_reverses_every_triangle():
    forward = polygontessellator.PolygonTessellator().tessContours(_ring(), normal=(0, 0, 1))
    backward = polygontessellator.PolygonTessellator(ccw=False).tessContours(
        _ring(), normal=(0, 0, 1))
    assert len(backward) == len(forward)
    assert all(_signed_area(t) < 0 for t in _triangles(backward))


def test_triangles_unforced_are_one_triangle_set(tessellator):
    primitives = tessellator.tessContours(_ring(), forceTriangles=0)
    (kind, vertices), = primitives
    assert kind == GL_TRIANGLES
    assert _area(vertices) == pytest.approx(_area(tessellator.tessContours(_ring())))


def test_a_crossing_makes_a_blended_vertex(tessellator):
    """A bow tie: the edges cross at (0.5, 0.5), and the colour there is between."""
    bowtie = [
        Vertex(point=(0, 0, 0), color=(1.0, 0.0, 0.0)),
        Vertex(point=(1, 1, 0), color=(0.0, 0.0, 1.0)),
        Vertex(point=(1, 0, 0), color=(1.0, 0.0, 0.0)),
        Vertex(point=(0, 1, 0), color=(0.0, 0.0, 1.0)),
    ]
    vertices = tessellator.tessellate(bowtie)
    invented = [v for v in vertices if all(v is not b for b in bowtie)]
    assert invented
    for vertex in invented:
        assert tuple(vertex.point) == pytest.approx((0.5, 0.5, 0.0))
        assert tuple(vertex.color) == pytest.approx((0.5, 0.0, 0.5))
    assert _area(vertices) == pytest.approx(0.5)


def test_the_winding_rule_decides_what_overlaps_fill():
    overlapping = [_square(0, 0, 2.0), _square(1, 1, 2.0)]
    odd = polygontessellator.PolygonTessellator().tessContours(overlapping)
    nonzero = polygontessellator.PolygonTessellator(
        windingRule=GLU_TESS_WINDING_NONZERO).tessContours(overlapping)
    assert _area(odd) == pytest.approx(6.0)
    assert _area(nonzero) == pytest.approx(7.0)


@pytest.mark.parametrize('points', [
    [],
    [(0, 0, 0), (1, 0, 0)],
    [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
    [(0, 0, 0), (1, 0, 0), (float('nan'), 1, 0), (0, 1, 0)],
], ids=['empty', 'two-points', 'collinear', 'not-finite'])
def test_a_degenerate_face_is_no_triangles(tessellator, points):
    assert tessellator.tessellate([Vertex(point=p) for p in points]) == []


def test_it_tessellates_where_glu_is_not_installed():
    """With PyOpenGL's GLU library absent, every GLU entry point is undefined."""
    script = '\n'.join([
        'from OpenGL import platform',
        'platform.PLATFORM.GLU = None',
        'from OpenGLContext.scenegraph import polygontessellator, vertex',
        'square = [vertex.Vertex(point=p) for p in',
        '          ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0.5, 1.5, 0), (0, 1, 0))]',
        'print(len(polygontessellator.PolygonTessellator().tessellate(square)))',
    ])
    done = subprocess.run([sys.executable, '-c', script],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.split()[-1] == '9'
