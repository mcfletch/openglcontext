"""KHR_lights_punctual spot cone loading (gltf.scene._light_node).

A KHR spot cone is given as half-angles from the axis (``spot.outerConeAngle`` /
``innerConeAngle``), which is exactly the VRML ``SpotLight.cutOffAngle`` /
``beamWidth`` convention, so the loader stores them as-is; it falls back to a
sensible default cone when the light omits ``spot``. No GL context needed:
_light_node is a pure builder.
"""
import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.scenegraph.basenodes import SpotLight, PointLight, DirectionalLight


WORLD = np.eye(4)


def test_spot_cone_half_angles_map_directly():
    light = {'type': 'spot', 'intensity': 3.0,
             'spot': {'innerConeAngle': 0.30, 'outerConeAngle': 0.90}}
    node = gltf.scene._light_node(light, WORLD)
    assert isinstance(node, SpotLight)
    # KHR half-angles are the VRML cutOffAngle/beamWidth convention: no scaling.
    assert node.cutOffAngle == pytest.approx(0.90)
    assert node.beamWidth == pytest.approx(0.30)


def test_spot_defaults_to_quarter_pi_cone_when_unspecified():
    node = gltf.scene._light_node({'type': 'spot'}, WORLD)
    assert isinstance(node, SpotLight)
    assert node.cutOffAngle == pytest.approx(np.pi / 4.0)   # outer defaults to pi/4


def test_spot_does_not_cast_shadows_by_default():
    node = gltf.scene._light_node({'type': 'spot'}, WORLD)
    assert not node.castShadows
    lit = gltf.scene._light_node({'type': 'spot', 'castShadows': True}, WORLD)
    assert lit.castShadows


def test_point_and_directional_unaffected_by_spot_handling():
    p = gltf.scene._light_node({'type': 'point'}, WORLD)
    assert isinstance(p, PointLight)
    d = gltf.scene._light_node({'type': 'directional'}, WORLD)
    assert isinstance(d, DirectionalLight)
    assert d.castShadows          # directionals still default to shadow casters
