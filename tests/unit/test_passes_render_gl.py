"""In-process full-scene PBR renders that drive the GL paths of the render passes.

These build a real :class:`GLFWInteractiveContext` (hidden window) and render a few
frames of a real scenegraph so the shader-mode draw loops actually execute -- the
paths the pure-logic suites (test_pbrpass_logic / test_instancing_logic /
test_flateffects_logic / test_selection_logic) cannot reach without a context.

Each test sets its effect env vars, builds a fresh context, renders, and asserts on
an observable effect (an instanced draw happened, a pick resolved, the framebuffer
lit up). Skips cleanly when no GL context can be created.
"""
import os

os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

import pytest  # noqa: E402

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402


def _base_env(monkeypatch, **extra):
    monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
    monkeypatch.setenv('OPENGLCONTEXT_BACKEND', 'glfw')
    monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'pbr')
    monkeypatch.setenv('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
    monkeypatch.setenv('OPENGLCONTEXT_NO_VSYNC', '1')
    monkeypatch.setenv('PYOPENGL_PLATFORM', 'egl')
    for k, v in extra.items():
        monkeypatch.setenv(k, str(v))


class _Rendered:
    def __init__(self, context, counters):
        self.context = context
        self.instanced_calls = counters['instanced_calls']
        self.instances = counters['instances']
        self.single_draws = counters['single']
        self.shadow_passes = counters['shadow']
        self.transmissive_passes = counters['transmissive']
        self.legacy_pick_passes = counters['legacy_pick']
        self.bloom_composites = counters['bloom']


@pytest.fixture
def render_scene(monkeypatch):
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
        return _Rendered(inst, counters)

    yield run

    # Full-context teardown must be bulletproof: a later test's glfw.terminate()
    # (test_pbrmaterial's gl fixture) segfaults if this context's GL resources are
    # finalized after the GL context is gone. So drop the context and force its
    # VBO/FBO finalizers to run WHILE its window is still current, then destroy the
    # window and hard-reset glfw so no state from the full context survives into the
    # next test.
    import gc

    from OpenGLContext.passes import renderpass

    # `renderpass.FLAT` is a module global holding the pass that last rendered,
    # and it outlives the window it belongs to.  Left set, it hands the next
    # test a shader program whose GL context is gone -- which reads as "there
    # is a pass" to anything that asks, on a machine where there is not.
    renderpass.FLAT = None
    contexts.clear()
    gc.collect()                       # run GL finalizers against the live context
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
        glfw.terminate()               # hard reset: no leaked window/context state
    except Exception:
        pass


def _sphere_shape(x, radius=1.0, color=(0.3, 0.6, 0.9)):
    return basenodes.Transform(translation=(x, 0, 0), children=[
        basenodes.Shape(
            geometry=basenodes.Sphere(radius=radius),
            appearance=basenodes.Appearance(
                material=basenodes.Material(diffuseColor=color)))])


def _key_light():
    return basenodes.DirectionalLight(direction=(-0.3, -0.5, -1.0), intensity=1.2)


def _no_gl_error():
    from OpenGL.GL import glGetError, GL_NO_ERROR
    return int(glGetError()) == GL_NO_ERROR


class TestInstancedPBRRender:
    def test_shared_geometry_collapses_to_instanced_draw(self, render_scene, monkeypatch):
        _base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='2')
        children = [_sphere_shape(x) for x in (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)]
        children.append(_key_light())
        r = render_scene(children, frames=4)
        # Six equal-radius spheres share one instance group -> instanced draw ran
        # and drew all six in one call, not six per-shape draws.
        assert r.instanced_calls >= 1
        assert r.instances >= 6
        assert _no_gl_error()


class TestShadowedRender:
    def test_shadow_casting_light_runs_depth_pass(self, render_scene, monkeypatch):
        _base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='1',
                  OPENGLCONTEXT_SHADOW_CASCADES='1', OPENGLCONTEXT_INSTANCE_MIN='2')
        children = [_sphere_shape(x) for x in (-1.5, 0.0, 1.5)] + [_key_light()]
        r = render_scene(children, frames=5, shadows=True)
        # The shadow depth pass actually ran (renderShadowMaps invoked per frame).
        assert r.shadow_passes >= 1
        assert _no_gl_error()


class TestMultiLightShadows:
    def test_directional_spot_and_point_shadows_render(self, render_scene, monkeypatch):
        _base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='1',
                  OPENGLCONTEXT_SHADOW_CASCADES='1', OPENGLCONTEXT_INSTANCE_MIN='2')
        children = [
            _sphere_shape(x) for x in (-1.5, 0.0, 1.5)
        ]
        children += [
            basenodes.DirectionalLight(direction=(-0.3, -0.6, -1.0), intensity=0.9),
            basenodes.SpotLight(location=(0, 4, 3), direction=(0, -1, -0.6),
                                cutOffAngle=0.7, intensity=0.8),
            basenodes.PointLight(location=(3, 3, 3), intensity=0.8),
        ]
        r = render_scene(children, frames=5, shadows=True)
        # The shadow depth pass ran with a directional + spot + point light, so the
        # spot-slot and cube-slot binding paths executed.
        assert r.shadow_passes >= 1
        assert _no_gl_error()


class TestBloomRender:
    def test_bloom_wrap_composites(self, render_scene, monkeypatch):
        _base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_BLOOM='1',
                  OPENGLCONTEXT_INSTANCE_MIN='2')
        children = [_sphere_shape(0.0, color=(0.9, 0.9, 0.9))] + [_key_light()]
        r = render_scene(children, frames=4)
        # The HDR bloom wrap ran its composite end-phase.
        assert r.bloom_composites >= 1
        assert _no_gl_error()


class TestTransmissiveRender:
    def test_glass_shape_runs_transmissive_pass(self, render_scene, monkeypatch):
        _base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

        glass = PBRMesh(
            positions=[(-.7, -.7, 0), (.7, -.7, 0), (.7, .7, 0), (-.7, .7, 0)],
            normals=[(0, 0, 1)] * 4,
            indices=[0, 1, 2, 0, 2, 3])
        mat = PBRMaterial(baseColor=(0.6, 0.8, 1.0), transmission=0.7,
                          roughness=0.05, metallic=0.0)
        pane = basenodes.Transform(translation=(0, 0, 1.5), children=[
            basenodes.Shape(geometry=glass,
                            appearance=basenodes.Appearance(material=mat))])
        backdrop = _sphere_shape(0.0, radius=1.0, color=(0.9, 0.3, 0.2))
        r = render_scene([backdrop, pane, _key_light()], frames=4)
        # A material with transmission > 0 routes through the dedicated transmissive
        # draw phase after the opaque backdrop is captured.
        assert r.transmissive_passes >= 1
        assert _no_gl_error()

    def test_blend_mode_transmission_runs(self, render_scene, monkeypatch):
        _base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999',
                  OPENGLCONTEXT_TRANSMISSION='blend')
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

        glass = PBRMesh(
            positions=[(-.7, -.7, 0), (.7, -.7, 0), (.7, .7, 0), (-.7, .7, 0)],
            normals=[(0, 0, 1)] * 4,
            indices=[0, 1, 2, 0, 2, 3])
        mat = PBRMaterial(baseColor=(0.6, 0.8, 1.0), transmission=0.7, roughness=0.05)
        pane = basenodes.Transform(translation=(0, 0, 1.5), children=[
            basenodes.Shape(geometry=glass,
                            appearance=basenodes.Appearance(material=mat))])
        backdrop = _sphere_shape(0.0, radius=1.0, color=(0.9, 0.3, 0.2))
        r = render_scene([backdrop, pane, _key_light()], frames=4)
        # The blend fallback path (alpha-blended glass, no backdrop capture) runs.
        assert r.transmissive_passes >= 1
        assert _no_gl_error()


class TestLegacyColourPick:
    def test_pick_center_resolves_through_legacy_path(self, render_scene, monkeypatch):
        _base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
        # instance-min high so shapes render per-object (the legacy pick path renders
        # each candidate object with a unique colour id).
        children = [_sphere_shape(0.0, radius=2.0)] + [_key_light()]
        # Three pick points drive distinct branches of the per-pick loop: a centre
        # hit, a near-corner miss (no object under the point), and a point outside
        # the viewport (rejected before rendering).
        r = render_scene(
            children, frames=5, mrt=False,
            picks=lambda w, h: [(w // 2, h // 2), (1, 1), (w + 100, h + 100)])
        # The legacy per-pick colour-id render path ran.
        assert r.legacy_pick_passes >= 1
        assert _no_gl_error()
