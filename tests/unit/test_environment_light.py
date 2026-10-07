"""X3D's EnvironmentLight as the scene's image-based light.

Its ``diffuseCoefficients`` are glTF's ``irradianceCoefficients`` (X3D 4.1,
17.4): nine RGB spherical-harmonic coefficients, here scaled by its ``color``.
It is drawn as an ``ImageBasedLight`` (``EnvironmentLight.imageLight``), with
its ``rotation`` and ``intensity``, and a single specular level made from
the same coefficients; the cube-map textures are not read.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.passes.zonepass import ZonesMixin
from OpenGLContext.scenegraph.environmentlight import EnvironmentLight
from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight

COEFFICIENTS = [0.5, 0.25, 0.125] + [0.0] * 24


def test_it_is_the_engines():
    assert prototypes()['EnvironmentLight'] is EnvironmentLight


def test_its_coefficients_are_an_image_lights():
    light = EnvironmentLight(diffuseCoefficients=COEFFICIENTS, color=(1, 0.5, 1), intensity=2.0)
    found = light.imageLight()
    assert isinstance(found, ImageBasedLight)
    coefficients = np.asarray(found.irradianceCoefficients)
    assert coefficients.shape == (9, 3)
    assert coefficients[0] == pytest.approx((0.5, 0.125, 0.125))
    assert found.intensity == pytest.approx(2.0)
    assert len(found.specular) == 1 and len(found.specular[0]) == 6


def test_its_rotation_is_a_quaternion():
    light = EnvironmentLight(diffuseCoefficients=COEFFICIENTS, rotation=(0, 1, 0, np.pi / 2))
    x, y, z, w = light.imageLight().rotation
    assert (x, z) == pytest.approx((0, 0), abs=1e-6)
    assert (y, w) == pytest.approx((np.sin(np.pi / 4), np.cos(np.pi / 4)))


@pytest.mark.parametrize('fields', [dict(on=False), dict(diffuseCoefficients=[1, 2, 3])])
def test_a_light_that_is_off_or_short_lights_nothing(fields):
    found = dict(diffuseCoefficients=COEFFICIENTS)
    found.update(fields)
    assert EnvironmentLight(**found).imageLight() is None


def test_an_edit_makes_a_new_image_light():
    light = EnvironmentLight(diffuseCoefficients=COEFFICIENTS)
    first = light.imageLight()
    assert light.imageLight() is first
    light.intensity = 3.0
    assert light.imageLight() is not first


def test_the_scene_is_lit_by_its_environment_light():
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    light = EnvironmentLight(diffuseCoefficients=COEFFICIENTS)
    held = SimpleNamespace(paths={x3d.EnvironmentLight: [(None, light)]})
    assert ZonesMixin.sceneImageLight(held) is light.imageLight()


def test_a_document_is_lit_by_its_environment_light(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL

    def middle(colour):
        scene = Loader.loads(b'''<X3D version="4.1"><Scene>
          <NavigationInfo headlight="false"/><Background skyColor="0 0 0"/>
          <Viewpoint position="0 0 4"/>
          <EnvironmentLight diffuseCoefficients="''' + colour + b''' 0 0 0 0 0 0 0 0 0 0 0 0
              0 0 0 0 0 0 0 0 0 0 0 0"/>
          <Shape><Appearance><PhysicalMaterial baseColor="1 1 1" roughness="1"
              metallic="0"/></Appearance><Sphere/></Shape>
        </Scene></X3D>''', 'scene.x3d')
        with scene_context(scene, size=(32, 32), ibl='full') as context:
            for _ in range(3):
                image = drawn_image(context)
        return image[16, 16].astype(int)

    # The environment replaces the studio's white one: each tints the sphere.
    red, blue = middle(b'3 0 0'), middle(b'0 0 3')
    assert red[0] > red[2] + 20
    assert blue[2] > blue[0] + 20
