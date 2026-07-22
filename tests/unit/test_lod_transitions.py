"""Measure the on-screen 'pop' and gap-freeness of quadric LOD transitions.

An earlier version of this test measured the pixel difference as a fraction of
the whole frame, at the threshold *distance* (where the object is tiny). That was
useless: it could not tell a smooth coarse sphere from one with a hole in it,
because both are only a few pixels far away. This version measures what actually
matters:

* **Pop** -- the fraction of the *object's own pixels* that change when it
  switches from one LOD level to the next, rendered LARGE (filling the frame).
  A violent halving of the mesh changes ~75% of the object; the tuned schedule
  keeps it small.  (The light is set under a fixed eye-space modelview so
  consecutive renders are lit identically -- otherwise the metric measures
  lighting noise, not geometry.)

* **Gap** -- LOD 2 of each shape, rendered solid with back-face culling on, must
  have no background bleeding through its interior (the off-by-one that left a
  pole cap / seam wedge missing on coarse quadrics).

Rendered fixed-function in a hidden GLFW (compatibility) context.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.quadrics import Sphere, Cone

glfw = pytest.importorskip('glfw')
from OpenGL.GL import *              # noqa: E402,F403
from OpenGL.GLU import gluPerspective  # noqa: E402

S = 256
PI = np.pi
# Max fraction of the object's own pixels that may change at a switch. The tuned
# schedule's worst step is ~14% (the far 16->12-gon sphere step); a mesh-halving
# schedule would be ~75%, and a gap far more, so this budget is a real gate.
MAX_OBJECT_POP = 0.20
# The up-close switch (L0->L1) must be nearly invisible.
MAX_NEAR_POP = 0.06
CHANNEL_DELTA = 12


@pytest.fixture(scope='module')
def gl_ctx():
    if not glfw.init():
        pytest.skip('GLFW could not initialise')
    # GLFW window hints are sticky/process-global; reset them so a prior
    # core-profile test's profile can't leak into this context.
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    win = glfw.create_window(S, S, 'lod', None, None)
    if not win:
        glfw.terminate()
        pytest.skip('GLFW could not create a window/context')
    glfw.make_context_current(win)
    yield win
    glfw.terminate()


def _coords(kind, level):
    """(coords, indices) for a unit quadric of ``kind`` at LOD ``level``."""
    from OpenGLContext.scenegraph.quadrics import lod_phi
    if kind == 'sphere':
        return Sphere(radius=1.0).compileArrays(level)
    phi = lod_phi(Cone._BASE_PHI, level, 2 * PI)
    if kind == 'cone':
        return Cone.cone(3.0, 1.0, True, True, phi=phi)
    return Cone.cone(3.0, 1.0, True, True, phi=phi, top=True, cylinder=True)


def _fbo():
    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    col = glGenRenderbuffers(1)
    glBindRenderbuffer(GL_RENDERBUFFER, col)
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, S, S)
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, col)
    dep = glGenRenderbuffers(1)
    glBindRenderbuffer(GL_RENDERBUFFER, dep)
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, S, S)
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, dep)
    ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
    return fbo, col, dep, ok


# Object orientations to render from. The axis views matter because the objects
# are NOT viewpoint-aligned: 'side' shows the barrel, but 'axis_top'/'axis_bottom'
# look straight down the Y axis -- the sphere's pole cap and the cone/cylinder end
# caps -- which is exactly where a closure gap hides and is invisible side-on.
VIEWS = {
    'side': (25.0, 1.0, 0.3, 0.0),
    'axis_top': (90.0, 1.0, 0.0, 0.0),
    'axis_bottom': (-90.0, 1.0, 0.0, 0.0),
}


def _render(coords, indices, cull=False, view='side', dist=2.8):
    v = np.ascontiguousarray(coords[:, 0:3], 'f')
    n = np.ascontiguousarray(coords[:, 5:8], 'f')
    idx = np.ascontiguousarray(indices, 'H')
    angle, ax, ay, az = VIEWS[view]
    fbo, col, dep, ok = _fbo()
    if not ok:
        glDeleteFramebuffers(1, [fbo]); glDeleteRenderbuffers(2, [col, dep])
        pytest.skip('offscreen FBO incomplete on this driver')
    try:
        glViewport(0, 0, S, S)
        glClearColor(0, 0, 0, 1)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        if cull:
            glEnable(GL_CULL_FACE); glCullFace(GL_BACK); glFrontFace(GL_CCW)
            glDisable(GL_LIGHTING)
        else:
            glDisable(GL_CULL_FACE); glEnable(GL_LIGHTING); glEnable(GL_LIGHT0)
        glEnable(GL_COLOR_MATERIAL); glColor3f(0.85, 0.85, 0.85)
        glMatrixMode(GL_PROJECTION); glLoadIdentity(); gluPerspective(45, 1, 0.1, 50)
        glMatrixMode(GL_MODELVIEW); glLoadIdentity()
        # Light set here, under the identity view, so it is a fixed eye-space
        # direction every call regardless of the object transform below.
        if not cull:
            glLightfv(GL_LIGHT0, GL_POSITION, [0.3, 0.5, 1.0, 0.0])
            glLightfv(GL_LIGHT0, GL_DIFFUSE, [1, 1, 1, 1])
        glTranslatef(0, 0, -dist)
        glRotatef(angle, ax, ay, az)
        glEnableClientState(GL_VERTEX_ARRAY); glEnableClientState(GL_NORMAL_ARRAY)
        glVertexPointer(3, GL_FLOAT, 0, v); glNormalPointer(GL_FLOAT, 0, n)
        glDrawElements(GL_TRIANGLES, len(idx), GL_UNSIGNED_SHORT, idx)
        glDisableClientState(GL_VERTEX_ARRAY); glDisableClientState(GL_NORMAL_ARRAY)
        raw = glReadPixels(0, 0, S, S, GL_RGB, GL_UNSIGNED_BYTE)
        return np.frombuffer(raw, np.uint8).reshape(S, S, 3).astype(np.int16)
    finally:
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glDeleteFramebuffers(1, [fbo]); glDeleteRenderbuffers(2, [col, dep])


def _object_pop(a, b):
    """Fraction of the object's pixels (either render) that change colour."""
    changed = np.abs(a - b).max(axis=2) > CHANNEL_DELTA
    obj = (a.max(axis=2) > 20) | (b.max(axis=2) > 20)
    return float(changed.sum()) / max(1, int(obj.sum()))


def _interior_holes(img):
    """Fraction of the silhouette interior showing background (a mesh gap)."""
    white = img.max(axis=2) > 40
    if white.sum() == 0:
        return 1.0
    row = np.zeros_like(white); col = np.zeros_like(white)
    for y in range(S):
        xs = np.where(white[y])[0]
        if len(xs):
            row[y, xs[0]:xs[-1] + 1] = True
    for x in range(S):
        ys = np.where(white[:, x])[0]
        if len(ys):
            col[ys[0]:ys[-1] + 1, x] = True
    inside = row & col
    return float((inside & ~white).sum()) / max(1, int(inside.sum()))


KINDS = ['sphere', 'cone', 'cylinder']
VIEW_NAMES = list(VIEWS)


@pytest.mark.core_profile
class TestQuadricLodPop:
    @pytest.mark.parametrize('view', VIEW_NAMES)
    @pytest.mark.parametrize('kind', KINDS)
    def test_every_transition_is_bounded(self, gl_ctx, kind, view):
        imgs = [_render(*_coords(kind, lvl), view=view) for lvl in range(4)]
        pops = [_object_pop(imgs[i], imgs[i + 1]) for i in range(3)]
        assert max(pops) <= MAX_OBJECT_POP, (
            f"{kind}/{view} LOD pops {[round(p, 3) for p in pops]} "
            f"(budget {MAX_OBJECT_POP})"
        )

    @pytest.mark.parametrize('view', VIEW_NAMES)
    @pytest.mark.parametrize('kind', KINDS)
    def test_near_transition_is_subtle(self, gl_ctx, kind, view):
        pop = _object_pop(_render(*_coords(kind, 0), view=view),
                          _render(*_coords(kind, 1), view=view))
        assert pop <= MAX_NEAR_POP, f"{kind}/{view} L0->L1 pop {pop:.3f}"

    def test_metric_catches_a_violent_halving(self, gl_ctx):
        """A sphere that halves its slice count (the old aggressive schedule)
        pops far past the budget -- proving the metric actually measures pop."""
        fine = _render(*Sphere(radius=1.0).sphere(PI / 12))
        halved = _render(*Sphere(radius=1.0).sphere(PI / 6))   # 24-gon -> 12-gon
        assert _object_pop(fine, halved) > MAX_OBJECT_POP


@pytest.mark.core_profile
class TestNoGapAtCoarseLod:
    """LOD 2 must render as a solid shape from every angle. This reliably catches
    the SPHERE gap -- side view catches a seam wedge, and the axis views catch a
    missing pole cap (verified: a non-dividing phi lights this up ~0.05 side /
    ~0.19 pole). It is only a solidity sanity check for the cone/cylinder, whose
    seam gap is backfilled on screen by the far wall; their precise closure guard
    is TestClosure in test_quadric_lod (phi divides 2*pi -> the ring closes)."""

    @pytest.mark.parametrize('view', VIEW_NAMES)
    @pytest.mark.parametrize('kind', KINDS)
    def test_lod2_renders_solid_no_interior_gap(self, gl_ctx, kind, view):
        holes = _interior_holes(_render(*_coords(kind, 2), cull=True, view=view))
        assert holes < 0.01, f"{kind}/{view} LOD2 shows an interior gap ({holes:.3f})"


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v', '-s']))
