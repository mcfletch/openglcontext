"""End-to-end drive of the optimized colour-pick render loop of
:class:`SelectionMixin` (``shaderSelectRenderOptimized``) in a real core-profile
GLFW context.

The fast MRT path is disabled (``use_mrt_selection = False``) so the pass falls
back to this per-pick-point loop: for each pick point it computes candidate
objects from their screen-space bounding boxes, renders them into a tiny FBO with
unique colour ids, reads the pixel under the point, and dispatches the resolved
object path to the event. These tests inject pick events at controlled positions
-- over a shape, over empty space inside the viewport, and outside the viewport --
and assert the object paths the loop resolves.

A ``Box`` is the pick target because its geometry renders through the core-profile
shader path; the quadric ``Sphere`` still uses legacy client-state calls that are
invalid in a core context.
"""
import os

os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

import pytest  # noqa: E402

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402
from OpenGLContext.events.mouseevents import MouseButtonEvent  # noqa: E402


@pytest.fixture
def pick_context(monkeypatch):
    """Build a warmed core-profile context whose selection uses the legacy loop.

    Returns ``build(children, warm=3) -> context`` and tears the window down
    afterwards. ``use_mrt_selection`` is forced off so picks route through
    ``shaderSelectRenderOptimized`` rather than the MRT id-buffer readback.
    """
    monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
    monkeypatch.setenv('OPENGLCONTEXT_BACKEND', 'glfw')
    monkeypatch.setenv('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
    monkeypatch.setenv('OPENGLCONTEXT_SHADOWS', '0')
    monkeypatch.setenv('OPENGLCONTEXT_NO_VSYNC', '1')
    monkeypatch.setenv('PYOPENGL_PLATFORM', 'egl')

    from OpenGLContext.passes import selection
    monkeypatch.setattr(selection.SelectionMixin, 'use_mrt_selection', False)

    # renderer_is_pbr() caches the OPENGLCONTEXT_RENDERER verdict process-wide on
    # first read. These tests run under the plain core pass (no pbr env), so clear
    # the cache here and again at teardown: otherwise a stale verdict leaks either
    # into or out of this fixture and flips another test's pass class.
    from OpenGLContext.passes import pbrpass
    pbrpass._renderer_is_pbr_cache = None

    windows = []
    contexts = []

    def build(children, warm=3):
        if not glfw.init():
            pytest.skip("glfw init failed")
        from OpenGLContext import testingcontext
        Base = testingcontext.getInteractive()
        sg = basenodes.sceneGraph(children=children)

        class _Ctx(Base):
            def OnInit(self):
                self.sg = sg
                self.contextDefinition.pickAsync = False
                self.addEventHandler('mousebutton', button=0, state=1,
                                     function=lambda e: None)

        try:
            inst = _Ctx()
        except Exception as err:      # pragma: no cover - only on a broken GL stack
            pytest.skip("no usable GL context: %r" % (err,))
        inst.deferRedraw = True
        win = getattr(inst, 'window', None)
        if win is not None:
            windows.append(win)
        try:
            glfw.swap_interval(0)
        except Exception:
            pass
        for _ in range(warm):
            glfw.poll_events()
            inst.OnDraw(force=1)
        contexts.append(inst)
        return inst

    yield build

    import gc
    contexts.clear()
    gc.collect()
    for win in windows:
        try:
            glfw.destroy_window(win)
        except Exception:
            pass
    try:
        glfw.make_context_current(None)
    except Exception:
        pass
    gc.collect()
    try:
        glfw.terminate()
    except Exception:
        pass
    pbrpass._renderer_is_pbr_cache = None


def _box_target(size=(4, 4, 4), color=(0.2, 0.8, 0.3)):
    """A pickable Box shape plus a key light; returns (target_shape, children)."""
    target = basenodes.Shape(
        geometry=basenodes.Box(size=size),
        appearance=basenodes.Appearance(
            material=basenodes.Material(diffuseColor=color)))
    children = [
        basenodes.Transform(children=[target]),
        basenodes.DirectionalLight(direction=(-0.3, -0.5, -1.0), intensity=1.2),
    ]
    return target, children


def _pick(x, y):
    ev = MouseButtonEvent()
    ev.button = 0
    ev.state = 1
    ev.modifiers = (0, 0, 0)
    ev.pickPoint = (x, y)
    return ev


def _drive_picks(inst, named_points):
    """Inject a distinct pick event per name and render one frame.

    Events go straight into ``pickEvents`` with distinct keys (``addPickEvent``
    keys by button/state/modifiers, which would collapse same-button clicks to
    one), so several pick points in different places resolve in a single frame.
    Returns {name: event} with each event's object paths populated.
    """
    events = {}
    picks = {}
    for name, (x, y) in named_points.items():
        ev = _pick(x, y)
        picks[name] = ev
        events[('mousebutton', (name,))] = ev
    inst.pickEvents = events
    glfw.poll_events()
    inst.OnDraw(force=1)
    return picks


def _resolves_to(event, node):
    paths = event.getObjectPaths()
    return bool(paths and paths[0] and paths[0][-1] is node)


class TestOptimizedColourPick:
    def test_pick_over_shape_resolves_its_path(self, pick_context):
        target, children = _box_target()
        inst = pick_context(children)
        w, h = inst.getViewPort()
        picks = _drive_picks(inst, {'hit': (w // 2, h // 2)})
        # Centre pick renders the box into the pick FBO, reads its colour id back,
        # and resolves the event to the box's scenegraph path with a real depth.
        assert _resolves_to(picks['hit'], target)
        vx, vy, depth = picks['hit'].viewCoordinate
        assert (vx, vy) == (w // 2, h // 2)
        assert 0.0 < depth < 1.0

    def test_pick_over_empty_space_resolves_nothing(self, pick_context):
        target, children = _box_target()
        inst = pick_context(children)
        w, h = inst.getViewPort()
        # (3, 3) is inside the viewport but outside the box's screen bbox: the loop
        # finds no candidate under the point and dispatches an empty path.
        picks = _drive_picks(inst, {'miss': (3, 3)})
        assert picks['miss'].getObjectPaths() == [[]]

    def test_pick_outside_viewport_is_rejected(self, pick_context):
        target, children = _box_target()
        inst = pick_context(children)
        w, h = inst.getViewPort()
        # Beyond the viewport the point is rejected before any rendering.
        picks = _drive_picks(inst, {'out': (w + 40, h + 40)})
        assert picks['out'].getObjectPaths() == [[]]

    def test_hit_miss_and_offscreen_resolve_together_in_one_frame(self, pick_context):
        target, children = _box_target()
        inst = pick_context(children)
        w, h = inst.getViewPort()
        picks = _drive_picks(inst, {
            'hit': (w // 2, h // 2),
            'miss': (3, 3),
            'out': (w + 40, h + 40),
        })
        assert _resolves_to(picks['hit'], target)
        assert picks['miss'].getObjectPaths() == [[]]
        assert picks['out'].getObjectPaths() == [[]]

    def test_pick_falls_back_to_scissor_when_fbo_bind_fails(self, pick_context,
                                                            monkeypatch):
        # With the pick FBO unavailable, the loop scissors the pick region of the
        # main framebuffer instead, renders there and reads it back. The pick must
        # still resolve to the shape.
        from OpenGLContext.passes import selectionbuffers
        monkeypatch.setattr(selectionbuffers.SelectionFBO, 'bind',
                            lambda self, *a: False)
        target, children = _box_target()
        inst = pick_context(children)
        w, h = inst.getViewPort()
        picks = _drive_picks(inst, {'hit': (w // 2, h // 2)})
        assert _resolves_to(picks['hit'], target)

    def test_object_without_screen_bounds_is_still_pickable(self, pick_context,
                                                            monkeypatch):
        # An object whose bounding volume yields no computable screen bbox is
        # conservatively included at every pick point rather than culled by the 2D
        # test. Force indeterminate bounds and confirm the shape still resolves.
        from OpenGLContext.passes import selection
        monkeypatch.setattr(
            selection.SelectionMixin, '_computeScreenSpaceBBoxes',
            lambda self, toRender, vp_w, vp_h: [None] * len(toRender))
        target, children = _box_target()
        inst = pick_context(children)
        w, h = inst.getViewPort()
        picks = _drive_picks(inst, {'hit': (w // 2, h // 2)})
        assert _resolves_to(picks['hit'], target)

    def test_empty_events_returns_before_touching_the_gpu(self, pick_context):
        target, children = _box_target()
        pick_context(children)          # warm a context so renderpass.FLAT exists
        from OpenGLContext.passes import renderpass
        fp = renderpass.FLAT
        before = fp._selection_fbo
        # No events: the loop returns immediately, never creating the pick FBO.
        fp.shaderSelectRenderOptimized(None, [], {})
        assert fp._selection_fbo is before

    def test_framebuffer_restore_failure_does_not_break_the_pick(self, pick_context,
                                                                 monkeypatch):
        # The finally-block guards the default-framebuffer rebind so a driver hiccup
        # there cannot leak out of the pick. Force that rebind to raise and confirm
        # the pick still resolved and the frame did not crash.
        from OpenGLContext.passes import selection

        def boom(*a, **k):
            raise RuntimeError("no current context")

        monkeypatch.setattr(selection, 'glBindFramebuffer', boom)
        target, children = _box_target()
        inst = pick_context(children)
        w, h = inst.getViewPort()
        picks = _drive_picks(inst, {'hit': (w // 2, h // 2)})
        assert _resolves_to(picks['hit'], target)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
