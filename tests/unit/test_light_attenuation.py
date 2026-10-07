"""How a point or spot light falls off with distance.

X3D (19775-1, 17.2.2.5): an X3D light's attenuation is
1 / max(attenuation[0] + attenuation[1] d + attenuation[2] d^2, 1), so it never
lights a surface close to it more than its intensity. glTF's punctual lights
fall off inverse-square with no such floor (KHR_lights_punctual).
"""
import numpy as np
import pytest

from OpenGLContext.passes.shaderpass import configure_light_from_node
from OpenGLContext.scenegraph.basenodes import PointLight, SpotLight


class Recording:
    """A shader program that records what each light is given"""

    def __init__(self):
        self.lights = []

    def set_light(self, index, **named):
        self.lights.append(named)


@pytest.mark.parametrize('kind', [PointLight, SpotLight])
def test_an_x3d_light_is_never_brighter_than_its_intensity(kind):
    program = Recording()
    configure_light_from_node(program, 0, kind(attenuation=(0, 1, 0)), np.identity(4))
    assert program.lights[0]['attenuation_floor'] == 1.0


@pytest.mark.parametrize('kind', ['point', 'spot'])
def test_a_gltf_light_falls_off_inverse_square(kind):
    from OpenGLContext.loaders.gltf import scene  # noqa: PLC0415 kept with its use
    light = scene._light_node({'type': kind}, np.identity(4))  # noqa: SLF001 one KHR_lights_punctual entry built without a document around it
    program = Recording()
    configure_light_from_node(program, 0, light, np.identity(4))
    assert program.lights[0]['attenuation_floor'] < 1e-3


WALL = b'''<X3D version="3.3"><Scene>
  <NavigationInfo headlight="false"/>
  <Viewpoint position="0 0 0"/>
  <PointLight location="0 0 -2.5" attenuation="%s" intensity="0.4"/>
  <Shape><Appearance><Material diffuseColor="1 1 1"/></Appearance>
    <IndexedFaceSet coordIndex="0 1 2 3">
      <Coordinate point="-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3"/></IndexedFaceSet></Shape>
</Scene></X3D>'''


def lit(attenuation):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(Loader.loads(WALL % attenuation, 'a.x3d'), size=(32, 32)) as context:
        drawn_image(context)
        return drawn_image(context)[16, 16].astype(int)


def test_close_to_an_x3d_light_it_is_its_intensity(gl_context):
    """Half a metre from a light falling off as 1/d, the wall is lit as by one
    that does not fall off"""
    assert lit(b'0 1 0') == pytest.approx(lit(b'1 0 0'), abs=3)
