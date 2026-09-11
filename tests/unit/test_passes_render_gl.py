"""In-process full-scene PBR renders that drive the GL paths of the render passes.

These build a real :class:`GLFWInteractiveContext` (hidden window) and render a few
frames of a real scenegraph so the shader-mode draw loops actually execute -- the
paths the pure-logic suites (test_pbrpass_logic / test_instancing_logic /
test_flateffects_logic / test_selection_logic) cannot reach without a context.

Each test sets its effect env vars, builds a fresh context, renders, and asserts on
an observable effect (an instanced draw happened, a pick resolved, the framebuffer
lit up). Skips cleanly when no GL context can be created.
"""

import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402
from tests.unit.glrender import base_env, frames_of  # noqa: E402,F401


def test_the_render_environment_does_not_adapt(monkeypatch):
    """A render that gets measured must not depend on how fast the machine is.

    Image-based lighting degrades and climbs back with the frame rate unless
    something pins it, so a test that renders and then counts pixels sees a
    different picture depending on what ran before it and how busy the GPU was
    by the time it started.  That is why a capture pins it, and a measured
    render is a capture in every respect that matters.  The shadow cascades are
    pinned here for the same reason.
    """
    from OpenGLContext.passes import ibl

    base_env(monkeypatch)
    assert not ibl.ibl_is_adaptive()
    assert ibl.resolve_ibl_mode(requested='auto') == 'analytic'


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
        base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='2')
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
        base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='1',
                  OPENGLCONTEXT_SHADOW_CASCADES='1', OPENGLCONTEXT_INSTANCE_MIN='2')
        children = [_sphere_shape(x) for x in (-1.5, 0.0, 1.5)] + [_key_light()]
        r = render_scene(children, frames=5, shadows=True)
        # The shadow depth pass actually ran (renderShadowMaps invoked per frame).
        assert r.shadow_passes >= 1
        assert _no_gl_error()


class TestMultiLightShadows:
    def test_directional_spot_and_point_shadows_render(self, render_scene, monkeypatch):
        base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='1',
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
        base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_BLOOM='1',
                  OPENGLCONTEXT_INSTANCE_MIN='2')
        children = [_sphere_shape(0.0, color=(0.9, 0.9, 0.9))] + [_key_light()]
        r = render_scene(children, frames=4)
        # The HDR bloom wrap ran its composite end-phase.
        assert r.bloom_composites >= 1
        assert _no_gl_error()


class TestTransmissiveRender:
    def test_glass_shape_runs_transmissive_pass(self, render_scene, monkeypatch):
        base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
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
        base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999',
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
        base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
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
