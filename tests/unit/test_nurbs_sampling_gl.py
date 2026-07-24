"""In-process GL tests for the GLU-backed NURBS sampling, trim and tessellation
paths.

``nurbssampling`` maps sampling nodes onto ``gluNurbsProperty`` calls, ``nurbstrim``
wraps the GLU trim primitives, and ``nurbstess._tessellate_nurbs_surface`` drives the
GLU tessellator. All three need a live GL context plus a real ``gluNewNurbsRenderer``
object, so they are exercised here against a hidden GLFW window.
"""
import os

import pytest

glfw = pytest.importorskip("glfw")

from OpenGL.GLU import gluDeleteNurbsRenderer, gluNewNurbsRenderer  # noqa: E402

from OpenGLContext.scenegraph import nurbs, nurbssampling  # noqa: E402
from OpenGLContext.scenegraph.nurbssampling import (  # noqa: E402
    NurbsDomainDistanceSample, NurbsToleranceSample, defaultSampling, initialise,
)
from OpenGLContext.scenegraph.nurbstess import _tessellate_nurbs_surface  # noqa: E402
from OpenGLContext.scenegraph.nurbstrim import (  # noqa: E402
    Contour2D, NurbsCurve2D, Polyline2D,
)

_KNOT = [0, 0, 0, 0, 1, 1, 1, 1]


@pytest.fixture
def gl_context():
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    if not glfw.init():
        pytest.skip("glfw init failed")
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    win = glfw.create_window(64, 64, "nurbs", None, None)
    if not win:
        pytest.skip("no GL window")
    glfw.make_context_current(win)
    saved = nurbssampling.object_space_tess
    yield win
    nurbssampling.object_space_tess = saved
    glfw.destroy_window(win)


@pytest.fixture
def nurb(gl_context):
    obj = gluNewNurbsRenderer()
    yield obj
    gluDeleteNurbsRenderer(obj)


def _surface(color=False):
    cps = [[x, y, 0] for y in range(4) for x in range(4)]
    kw = dict(controlPoint=cps, uDimension=4, vDimension=4, uKnot=_KNOT, vKnot=_KNOT)
    if color:
        kw['color'] = [[x / 3.0, y / 3.0, 0.5] for y in range(4) for x in range(4)]
    return nurbs.NurbsSurface(**kw)


class TestExtensionProbe:
    def test_initialise_probes_the_extension(self, gl_context):
        nurbssampling.object_space_tess = None
        result = initialise()
        assert result is True or result is False           # a real bool from GLU
        assert nurbssampling.object_space_tess is not None  # probe cached the answer

    def test_initialise_caches_probe(self, gl_context):
        nurbssampling.object_space_tess = 0     # simulate extension unavailable
        assert initialise() is False            # returns cached falsy, no re-probe

    def test_default_sampling_uses_object_space_when_available(self, gl_context):
        nurbssampling.object_space_tess = 1
        node = defaultSampling()
        assert node.method == "object"

    def test_default_sampling_falls_back_to_screen(self, gl_context):
        nurbssampling.object_space_tess = 0
        node = defaultSampling()
        assert node.method == "screen"


class TestToleranceSampleProperties:
    def test_screen_parametric_tolerance(self, nurb):
        node = NurbsToleranceSample(method="screen", parametric=1, tolerance=0.4)
        node.properties(nurb)                    # sets GLU_PARAMETRIC_TOLERANCE

    def test_screen_non_parametric_tolerance(self, nurb):
        node = NurbsToleranceSample(method="screen", parametric=0, tolerance=30.0)
        node.properties(nurb)                    # sets GLU_SAMPLING_TOLERANCE

    def test_object_method_when_extension_present(self, nurb):
        nurbssampling.object_space_tess = 1
        node = NurbsToleranceSample(method="object", parametric=1, tolerance=5)
        node.properties(nurb)
        assert node.method == "object"           # stayed object-space

    def test_object_method_downgrades_when_extension_absent(self, nurb, caplog):
        nurbssampling.object_space_tess = 0
        node = NurbsToleranceSample(method="object", parametric=0, tolerance=5)
        node.properties(nurb)
        assert node.method == "screen"           # downgraded to screen sampling
        assert any("object" in r.message for r in caplog.records)

    def test_unknown_method_warns_and_is_ignored(self, nurb, caplog):
        node = NurbsToleranceSample(method="bogus", parametric=0, tolerance=5)
        node.properties(nurb)
        assert any("unknown type" in r.message for r in caplog.records)


class TestDomainDistanceProperties:
    def test_sets_u_and_v_step(self, nurb):
        node = NurbsDomainDistanceSample(uStep=25.0, vStep=35.0)
        node.properties(nurb)                    # GLU_U_STEP / GLU_V_STEP


class TestTessellationSamplingBranches:
    def test_domain_distance_sampling_node(self, gl_context):
        cb = _tessellate_nurbs_surface(
            _surface(), sampling=NurbsDomainDistanceSample(uStep=20, vStep=20))
        assert len(cb.vertices) > 0

    def test_tolerance_sampling_node(self, gl_context):
        cb = _tessellate_nurbs_surface(
            _surface(),
            sampling=NurbsToleranceSample(method="screen", parametric=0, tolerance=30))
        assert len(cb.vertices) > 0

    def test_color_surface_emits_colors(self, gl_context):
        cb = _tessellate_nurbs_surface(_surface(color=True), u_step=20, v_step=20)
        assert cb._has_colors is True
        assert len(cb.colors) == len(cb.vertices)

    def test_default_sampling_without_node_or_steps(self, gl_context):
        # No sampling node and no explicit steps -> the built-in domain-distance default.
        cb = _tessellate_nurbs_surface(_surface(), sampling=None)
        assert len(cb.vertices) > 0

    def test_texcoord_map_emits_parametric_uv(self, gl_context):
        cb = _tessellate_nurbs_surface(_surface(), u_step=20, v_step=20, texcoord=True)
        assert len(cb.texcoords) == len(cb.vertices)
        us = [u for (u, _v) in cb.texcoords]
        vs = [v for (_u, v) in cb.texcoords]
        assert min(us) < 0.05 and max(us) > 0.95   # spans the 0..1 parametric domain
        assert min(vs) < 0.05 and max(vs) > 0.95


class TestTrimmedTessellation:
    def test_polyline_and_curve_trim_reduce_surface(self, gl_context):
        # Outer boundary is a closed polyline; the inner hole is one closed loop
        # built from a NURBS curve joined to a polyline (redbook trim.c layout).
        outer = Contour2D(
            children=[Polyline2D(point=[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]])])
        inner = Contour2D(children=[
            NurbsCurve2D(
                knot=_KNOT,
                controlPoint=[[0.25, 0.5], [0.25, 0.75], [0.75, 0.75], [0.75, 0.5]]),
            Polyline2D(point=[[0.75, 0.5], [0.5, 0.25], [0.25, 0.5]]),
        ])
        full = len(_tessellate_nurbs_surface(_surface(), u_step=20, v_step=20).vertices)
        trimmed = _tessellate_nurbs_surface(
            _surface(), trimming_contours=[outer, inner], u_step=20, v_step=20)
        assert len(trimmed.vertices) > 0             # trim ran, produced geometry
        assert len(trimmed.vertices) != full         # trimming reshaped the tessellation


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
