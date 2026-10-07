"""The names the shadow fields had before X3D's are still accepted.

X3D calls a light's switch `shadows` and a shape's `castShadow`; the engine
called them `castShadows` and `castsShadow`. Code written against the engine's
names constructs, reads and writes through them.
"""
import pytest

from OpenGLContext.scenegraph.basenodes import DirectionalLight, PointLight, Shape, SpotLight


@pytest.mark.parametrize('kind', [PointLight, SpotLight, DirectionalLight])
def test_a_lights_cast_shadows_is_shadows(kind):
    light = kind(castShadows=False)
    assert light.shadows is False or light.shadows == 0
    light.castShadows = True
    assert light.shadows and light.castShadows


def test_a_shapes_casts_shadow_is_cast_shadow():
    shape = Shape(castsShadow=False)
    assert not shape.castShadow
    shape.castsShadow = True
    assert shape.castShadow and shape.castsShadow
