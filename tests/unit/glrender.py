"""Rendering a real scenegraph in a real context, for the suites that need one.

These build a hidden-window :class:`GLFWInteractiveContext` and render a few
frames of a real scenegraph, so the shader-mode draw loops actually run -- the
paths the pure-logic suites (``test_pbrpass_logic``, ``test_instancing_logic``,
``test_flateffects_logic``, ``test_selection_logic``) cannot reach without a
context.  Seven modules ask for the same thing, so it is written once, here,
rather than imported out of whichever of them happens to hold it.

``tests/unit/conftest.py`` offers the :func:`render_scene` factory as a fixture,
which is what a test asks for; the rest is importable::

    from tests.unit.glrender import base_env, frames_of

The GL fixtures a *project built on the engine* uses ship in
``OpenGLContext.testing.plugin``; this is the engine's own instrumentation for
its render passes, which counts what each pass did.
"""

import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402,F401


def base_env(monkeypatch, **extra):
    monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
    monkeypatch.setenv('OPENGLCONTEXT_BACKEND', 'glfw')
    monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'pbr')
    monkeypatch.setenv('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
    monkeypatch.setenv('OPENGLCONTEXT_NO_VSYNC', '1')
    # Pinned, not left on auto.  Image-based lighting starts at the mode the
    # GPU supports and degrades when the recent frame rate sags, so a test that
    # renders a handful of frames -- reporting almost no frame rate yet -- drops
    # to 'analytic', while the same test after a warmed-up neighbour sometimes
    # does not.  That is a coin toss on the picture every measured render then
    # judges.  'analytic' is what these renders have always effectively had, so
    # pinning it changes no assertion and removes the toss.
    monkeypatch.setenv('OPENGLCONTEXT_IBL', 'analytic')
    monkeypatch.setenv('PYOPENGL_PLATFORM', 'egl')
    for k, v in extra.items():
        monkeypatch.setenv(k, str(v))


def frames_of(render_scene, children, **named):
    """Every finished frame ``children`` draws, as an (H, W, 3) array each.

    Read inside ``SwapBuffers``, which is the only moment a finished frame is
    still in the back buffer -- after the swap it is gone, and a core-profile
    context will not let the front buffer be read at all. It is also where
    ``SettleCapture`` reads, so this sees what a screenshot would.
    """
    from OpenGLContext.capture import read_back_buffer
    from OpenGLContext import glfwcontext

    frames = []
    original = glfwcontext.GLFWContext.SwapBuffers

    def capturing(self):
        frames.append(read_back_buffer()[0])
        return original(self)

    glfwcontext.GLFWContext.SwapBuffers = capturing
    try:
        render_scene(children, **named)
    finally:
        glfwcontext.GLFWContext.SwapBuffers = original
    assert frames, 'the scene drew no frames at all'
    return frames


class Rendered:
    def __init__(self, context, counters):
        self.context = context
        self.instanced_calls = counters['instanced_calls']
        self.instances = counters['instances']
        self.single_draws = counters['single']
        self.shadow_passes = counters['shadow']
        self.transmissive_passes = counters['transmissive']
        self.legacy_pick_passes = counters['legacy_pick']
        self.bloom_composites = counters['bloom']


def render_scene_factory(monkeypatch):
    """Factory: build a context around a scenegraph and render frames.

    Returns a callable(children, frames=4, picks=None, mrt=True) -> _Rendered and
    tears the window down afterward.
    """
    windows = []
    contexts = []

    def run(children, frames=4, picks=None, mrt=True, shadows=None):
        from OpenGLContext.passes import (
            instancing, selection, flateffects, shadowmixin, pbrpass, flatcore,
        )
        from OpenGLContext.scenegraph import pbrmesh

        if shadows is not None:
            # use_shadows is a class attribute resolved from the environment at
            # import time, so set it directly for a deterministic per-test verdict.
            monkeypatch.setattr(pbrpass.PBRPass, 'use_shadows', shadows, raising=False)
            monkeypatch.setattr(flatcore.FlatPass, 'use_shadows', shadows, raising=False)

        counters = {'instanced_calls': 0, 'instances': 0, 'single': 0,
                    'shadow': 0, 'transmissive': 0, 'legacy_pick': 0, 'bloom': 0}
        orig_draw = instancing.draw_instanced_mesh

        def counting_draw(gpu, mvs, oids, material_indices=None, **named):
            counters['instanced_calls'] += 1
            counters['instances'] += len(mvs)
            return orig_draw(gpu, mvs, oids, material_indices)

        monkeypatch.setattr(instancing, 'draw_instanced_mesh', counting_draw)

        orig_single = pbrmesh._MeshGPU.draw

        def counting_single(self):
            counters['single'] += 1
            return orig_single(self)

        monkeypatch.setattr(pbrmesh._MeshGPU, 'draw', counting_single)

        def _spy(cls, name, key):
            orig = getattr(cls, name)

            def wrapper(self, *a, **k):
                counters[key] += 1
                return orig(self, *a, **k)

            monkeypatch.setattr(cls, name, wrapper)

        _spy(shadowmixin.ShadowMapMixin, 'renderShadowMaps', 'shadow')
        _spy(flateffects._FlatEffectsMixin, 'shaderRenderTransmissive', 'transmissive')
        _spy(flateffects._FlatEffectsMixin, '_end_bloom', 'bloom')
        _spy(selection.SelectionMixin, 'shaderSelectRenderOptimized', 'legacy_pick')

        if not mrt:
            monkeypatch.setattr(selection.SelectionMixin, 'use_mrt_selection', False)

        if not glfw.init():
            pytest.skip("glfw init failed")

        from OpenGLContext import testingcontext
        Base = testingcontext.getInteractive()

        sg = basenodes.sceneGraph(children=children)

        class _Ctx(Base):
            def OnInit(self):
                self.sg = sg
                if picks is not None:
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

        from OpenGLContext.events.mouseevents import MouseButtonEvent
        w, h = inst.getViewPort()
        pick_points = picks(w, h) if callable(picks) else picks
        for i in range(frames):
            glfw.poll_events()
            if pick_points is not None and 1 <= i <= 2:
                for (px, py) in pick_points:
                    ev = MouseButtonEvent()
                    ev.button = 0
                    ev.state = 1
                    ev.modifiers = (0, 0, 0)
                    ev.pickPoint = (px, py)
                    inst.addPickEvent(ev)
                inst.triggerPick()
            inst.OnDraw(force=1)

        contexts.append(inst)
        return Rendered(inst, counters)

    yield run

    # The window goes back through the context that owns it --
    # `GLFWContext.releaseWindow`, which is what a user's application runs on
    # exit. It drops this context's GL objects from the engine's caches while
    # the context is still current, then destroys the window; and it is
    # idempotent, which is what makes it safe after a test has already driven
    # `OnQuit`. Destroying the handle here instead is a second free of a window
    # the context released, which the driver reports from wherever the freed
    # memory is next touched.
    import gc

    from OpenGLContext.passes import renderpass

    for inst in contexts:
        inst.releaseWindow()
    # `renderpass.FLAT` is a module global holding the pass that last rendered,
    # and it outlives the window it belongs to.  Left set, it hands the next
    # test a shader program whose GL context is gone -- which reads as "there
    # is a pass" to anything that asks, on a machine where there is not.
    renderpass.FLAT = None
    contexts.clear()
    windows.clear()
    gc.collect()
    try:
        glfw.make_context_current(None)
    except Exception:
        pass
    gc.collect()
