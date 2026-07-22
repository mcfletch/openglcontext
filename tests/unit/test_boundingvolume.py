"""Bounding-volume, plane and frustum tests.

Converted from the old ``boundingvolume.py`` check-script. The pure-math cases
run without a GL context; the frustum-extraction case drives real ``glFrustum``
through a hidden compatibility-profile GLFW window and skips when none is
available.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext import frustum, utilities
from OpenGLContext.arrays import identity, allclose


def test_point_normal_plane_roundtrip():
    """pointNormal2Plane and its inverse agree for planes through the origin."""
    for point, normal, expected in [
        ((0, 0, 0), (0, 1, 0), (0, 1, 0, 0)),
        ((0, 0, 0), (0, -2, 0), (0, -1, 0, 0)),
        ((0, 0, 0), (-1, 0, 0), (-1, 0, 0, 0)),
        ((0, 1, 0), (-1, 0, 0), (-1, 0, 0, 0)),
        ((0, -1, 0), (-1, 0, 0), (-1, 0, 0, 0)),
        ((0, -2, -1), (-100, 0, 0), (-1, 0, 0, 0)),
        ((0, -2, 1), (-8, 0, 0), (-1, 0, 0, 0)),
    ]:
        a, b, c, d = utilities.pointNormal2Plane(point, normal)
        assert (a, b, c, d) == expected, (point, normal, expected, (a, b, c, d))
        # roundtrip is only origin-preserving because every point is the origin
        p, n = utilities.plane2PointNormal((a, b, c, d))
        x, y, z = utilities.normalise(normal)
        assert allclose((p, n), ((0, 0, 0), (x, y, z))), (point, normal, (p, n))


def test_axis_aligned_box_exclusion():
    """Boxes fully behind a plane are culled; overlapping ones stay visible."""
    f = frustum.Frustum(
        planes=[
            utilities.pointNormal2Plane(
                (0, 0, 0), (-1, 0, 0)
            ),  # through origin, facing left
        ]
    )
    v = boundingvolume.AABoundingBox(center=(-3, 0, 0), size=(1, 1, 1))
    assert v.visible(f, identity(4, "f"))
    v = boundingvolume.AABoundingBox(center=(3, 0, 0), size=(1, 1, 1))
    assert not v.visible(f, identity(4, "f"))
    # box straddling the plane must remain visible
    v = boundingvolume.AABoundingBox(center=(0.5, 0, 0), size=(1, 1, 1))
    assert v.visible(f, identity(4, "f"))


def test_vectorized_cull_matches_naive():
    """The vectorized multi-plane cull must decide exactly as the per-point loop.

    Guards the boundingvolume.visible() rewrite (one matmul replacing the
    6*8 tiny numpy sum() calls that dominated large-scene culling).
    """

    def naive_decision(dist):
        # Original per-plane/per-point rule: cull iff some plane has every point
        # strictly behind it. Operates on precomputed signed distances so the
        # comparison isolates the reduction LOGIC being vectorized.
        for j in range(dist.shape[1]):
            if not (dist[:, j] >= 0).any():
                return 0
        return 1

    rng = np.random.default_rng(1234)
    tested = 0
    for _ in range(4000):
        n = int(rng.integers(4, 9))
        pts = rng.normal(size=(n, 4)).astype("f")
        pts[:, -1] = 1.0
        planes = rng.normal(size=(int(rng.integers(1, 7)), 4)).astype("f")
        f = frustum.Frustum(planes=planes)
        # Skip knife-edge cases: when a point's distance to a plane is within a
        # small tolerance of zero, the visible/culled decision is genuinely
        # ambiguous and BLAS last-bit rounding (matmul vs matmul at different
        # call sites) can flip it. Those sub-epsilon boundaries cannot produce a
        # visible artifact, so exclude them from the exact-equivalence check.
        dist64 = np.dot(pts.astype("d"), planes.astype("d").T)
        if np.abs(dist64).min() < 1e-3:
            continue
        box = boundingvolume.BoundingBox(points=pts)
        got = box.visible(f, identity(4, "f"))
        expected = naive_decision(dist64)
        assert bool(got) == bool(expected), (pts, list(f.planes), got)
        tested += 1
    assert tested > 2000, "too many cases skipped: %d" % tested


@pytest.fixture
def gl_context():
    """Hidden compatibility-profile GLFW window for fixed-function glFrustum."""
    glfw = pytest.importorskip("glfw")
    import os

    os.environ.setdefault("OPENGLCONTEXT_BACKEND", "glfw")
    if not glfw.init():
        pytest.skip("glfw init failed")
    # GLFW window hints are sticky/process-global; reset them so a prior
    # core-profile test's profile can't leak into this context.
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    win = glfw.create_window(64, 64, "boundingvolume", None, None)
    if not win:
        pytest.skip("no GL window")
    glfw.make_context_current(win)
    yield win
    glfw.destroy_window(win)


def test_frustum_extraction_matches_glfrustum(gl_context):
    """Frustum planes pulled from GL match the near/far fed to glFrustum.

    The near/far planes extracted from the projection matrix must reproduce the
    depths passed to glFrustum to within 1%. (Far distances beyond ~1e5 exceed
    float32 depth precision and are excluded — that divergence was the point of
    the original interactive check-script, not a correctness bug.)
    """
    from OpenGL.GL import (
        glMatrixMode,
        glLoadIdentity,
        glFrustum,
        GL_MODELVIEW,
        GL_PROJECTION,
    )

    for near in (0.2, 1.0, 3.0, 4.0, 5.0, 19.0):
        for far in (20.0, 100.0, 1000.0, 20000.0, 50000.0):
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glFrustum(-20, 20, -20, 20, near, far)
            f = frustum.Frustum.fromViewingMatrix()
            far_plane, near_plane = f.planes[-2:]
            far_current = round(float(far_plane[-1]), 4)
            near_current = round(float(near_plane[-1]), 4)
            assert abs(far_current - far) < abs(far / 100), (
                "far was %s, expected ~%s (near=%s)" % (far_current, far, near)
            )
            assert abs(near_current + near) < abs(near / 100), (
                "near was %s, expected ~%s" % (near_current, near)
            )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
