"""A light zones confine draws no shadow map while none of its zones is in view (GL).

A sun a ``ZoneLights`` names lights only what is in that zone, so with the
zone far out of every view nothing it lights is seen, and the pass draws no
cascades for it. With the zone in view, or with no zone naming the sun, the
cascades are drawn.
"""
import pytest

from OpenGLContext.passes import shadowmixin
from OpenGLContext.scenegraph.basenodes import (
    Box, DirectionalLight, Shape, Transform, Zone, ZoneLights,
)
from tests.unit.glrender import base_env


@pytest.fixture
def lit(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='1', OPENGLCONTEXT_SHADOW_CASCADES='1')
    drawn = []
    real = shadowmixin.ShadowMapMixin._renderLight

    def recording(self, path, light_node, *args, **named):
        drawn.append(light_node)
        return real(self, path, light_node, *args, **named)
    monkeypatch.setattr(shadowmixin.ShadowMapMixin, '_renderLight', recording)
    return drawn


def _scene(zone_at):
    sun = DirectionalLight(direction=(-0.3, -1.0, -0.2), castShadows=True)
    children = [
        Transform(translation=(0.0, -1.0, -5.0), children=[
            Shape(geometry=Box(size=(8.0, 0.2, 8.0)))]),
        Transform(translation=(0.0, 0.0, -5.0), children=[
            Shape(geometry=Box(size=(1.0, 1.0, 1.0)))]),
        sun,
    ]
    if zone_at is not None:
        children.append(Transform(translation=zone_at, children=[
            Zone(size=(10.0, 10.0, 10.0), settings=[ZoneLights(lights=[sun])])]))
    return sun, children


def test_a_zone_light_out_of_view_draws_no_shadow(render_scene, lit):
    sun, children = _scene((0.0, 0.0, 500.0))
    render_scene(children, shadows=True)
    assert sun not in lit


def test_a_zone_light_in_view_draws_its_shadow(render_scene, lit):
    sun, children = _scene((0.0, 0.0, -5.0))
    render_scene(children, shadows=True)
    assert sun in lit


def test_a_light_no_zone_names_draws_its_shadow(render_scene, lit):
    sun, children = _scene(None)
    render_scene(children, shadows=True)
    assert sun in lit
