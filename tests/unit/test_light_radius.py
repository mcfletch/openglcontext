"""A point or spot light's ``radius``: no light reaches past it.

VRML97's and X3D's PointLight and SpotLight light only what is within
``radius`` of them, in their own coordinates; within it they attenuate as
``attenuation`` says. The shader paths cut the light off there.
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
def test_the_radius_reaches_the_shader_in_eye_space(kind):
    program = Recording()
    scaled = np.diag([2.0, 2.0, 2.0, 1.0])
    configure_light_from_node(program, 0, kind(radius=5.0), scaled)
    assert program.lights[0]['light_radius'] == pytest.approx(10.0)


@pytest.mark.parametrize('kind', [PointLight, SpotLight])
def test_a_light_made_in_code_reaches_everywhere(kind):
    program = Recording()
    configure_light_from_node(program, 0, kind(), np.identity(4))
    assert program.lights[0]['light_radius'] == 0.0


@pytest.mark.parametrize('text, name', [
    (b'<X3D version="4.0"><Scene><PointLight/><SpotLight/></Scene></X3D>', 'scene.x3d'),
    (b'#VRML V2.0 utf8\nPointLight {} SpotLight {}\n', 'scene.wrl'),
])
def test_a_documents_light_has_the_declared_radius(text, name):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    point, spot = Loader.loads(text, name).children
    assert (float(point.radius), float(spot.radius)) == (100.0, 100.0)


SCENE = b'''<X3D version="4.0"><Scene>
  <NavigationInfo headlight="false"/>
  <Background skyColor="0 0 0"/>
  <Viewpoint position="0 0 0"/>
  <PointLight location="0 0 0" radius="%s" intensity="%s"/>
  <Transform translation="0 0 -20"><Shape>
    <Appearance><Material diffuseColor="1 1 1"/></Appearance><Box size="30 30 1"/>
  </Shape></Transform>
</Scene></X3D>'''


def brightness(radius, intensity=1.0, **definition):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(SCENE % (str(radius).encode(), str(intensity).encode()),
                         'scene.x3d')
    with scene_context(scene, size=(48, 48), **definition) as context:
        drawn_image(context)
        image = drawn_image(context)
    return float(np.asarray(image[16:32, 16:32], dtype=float).mean())


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_a_wall_past_the_radius_is_unlit(gl_context, renderer):
    """Past the radius the wall is as it is under a light of no intensity"""
    unlit = brightness(50.0, intensity=0.0, renderer=renderer)
    assert brightness(50.0, renderer=renderer) > unlit + 50
    assert brightness(10.0, renderer=renderer) == pytest.approx(unlit, abs=1.0)


def test_an_infinite_radius_is_unbounded():
    program = Recording()
    configure_light_from_node(program, 0, PointLight(radius=float('inf')), np.identity(4))
    assert program.lights[0]['light_radius'] == 0.0


def test_a_radius_of_zero_lights_nothing():
    program = Recording()
    configure_light_from_node(program, 0, PointLight(radius=0.0), np.identity(4))
    assert 0.0 < program.lights[0]['light_radius'] < 1e-3


@pytest.mark.parametrize('extra, expected', [({}, float('inf')), ({'range': 25.0}, 25.0)])
def test_a_gltf_light_reaches_its_range_or_everywhere(extra, expected):
    from OpenGLContext.loaders.gltf import scene  # noqa: PLC0415 kept with its use
    light = scene._light_node({'type': 'point', **extra}, np.identity(4))  # noqa: SLF001 one KHR_lights_punctual entry built without a document around it
    assert float(light.radius) == expected
