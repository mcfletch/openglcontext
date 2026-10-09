"""The compatibility profile's lights: their scope and their radius.

The fixed-function pipeline has no per-fragment cut-off, so a draw is lit by
the lights whose scope holds it and whose radius reaches its bounds: each
other light is switched off for that draw (`passes.lightscope.reach_mask`).
"""
import numpy as np
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.passes import lightscope
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.scenes import drawn_image, scene_context

COMPATIBILITY = {'OPENGLCONTEXT_PROFILE': 'compatibility', 'OPENGLCONTEXT_IBL': 'off'}


class TestReach:
    def setup_method(self):
        self.reaching = lightscope.reaching_lights([
            (0, basenodes.PointLight(location=(0, 0, 0), radius=5.0), np.identity(4)),
            (1, basenodes.DirectionalLight(), np.identity(4)),
            (2, basenodes.PointLight(location=(0, 0, 0)), np.identity(4)),
        ])

    def test_only_lights_with_a_finite_radius_are_kept(self):
        assert [slot for slot, _centre, _radius in self.reaching] == [0]

    def test_a_box_within_the_radius_is_reached(self):
        assert lightscope.reach_mask(self.reaching, (3, -1, -1), (4, 1, 1)) == 0

    def test_a_box_past_the_radius_is_not(self):
        assert lightscope.reach_mask(self.reaching, (6, -1, -1), (7, 1, 1)) == 0b1

    def test_a_box_round_the_light_is_reached(self):
        assert lightscope.reach_mask(self.reaching, (-50, -50, -50), (50, 50, 50)) == 0

    def test_the_corner_counts_not_the_face(self):
        # The nearest point of the box is (4, 4, 0), 5.66 from the light.
        assert lightscope.reach_mask(self.reaching, (4, 4, -1), (6, 6, 1)) == 0b1

    def test_the_lights_transform_moves_and_scales_it(self):
        placed = np.diag([2.0, 2.0, 2.0, 1.0])
        placed[3, :3] = (10, 0, 0)
        reaching = lightscope.reaching_lights(
            [(3, basenodes.SpotLight(location=(1, 0, 0), radius=4.0), placed)])
        (slot, centre, radius), = reaching
        assert slot == 3 and radius == pytest.approx(8.0)
        assert np.allclose(centre, (12, 0, 0))
        assert lightscope.reach_mask(reaching, (19, 0, 0), (20, 1, 1)) == 0
        assert lightscope.reach_mask(reaching, (21, 0, 0), (22, 1, 1)) == 0b1000

    def test_no_reaching_lights_is_no_mask(self):
        assert lightscope.reach_mask((), (0, 0, 0), (1, 1, 1)) == 0


def _centre(context):
    image = drawn_image(context)
    h, w = image.shape[:2]
    return image[h // 2, w // 2].astype(int)


@pytest.mark.parametrize('inside, lit', [(True, True), (False, False)])
def test_a_scoped_light_lights_only_its_siblings(gl_context_compat, inside, lit):
    light = basenodes.DirectionalLight(direction=(0, 0, -1))
    setattr(light, 'global', False)
    box = basenodes.Shape(geometry=basenodes.Box(size=(3, 3, 3)),
                          appearance=basenodes.Appearance(material=basenodes.Material(
                              diffuseColor=(1, 1, 1))))
    group = basenodes.Group(children=[light, box] if inside else [light])
    children = [basenodes.Viewpoint(position=(0, 0, 8)), basenodes.NavigationInfo(headlight=False),
                group] + ([] if inside else [box])
    with scene_context(children, environment=COMPATIBILITY) as context:
        context.OnDraw(force=1)
        brightness = _centre(context).sum()
    assert bool(brightness > 150) == lit


SCENE = b'''<X3D version="4.0"><Scene>
  <NavigationInfo headlight="false"/>
  <Background skyColor="0 0 0"/>
  <Viewpoint position="0 0 0"/>
  <PointLight location="0 0 0" radius="%s" intensity="%s" attenuation="1 0 0"/>
  <Transform translation="0 0 -20"><Shape>
    <Appearance><Material diffuseColor="1 1 1"/></Appearance><Box size="30 30 1"/>
  </Shape></Transform>
</Scene></X3D>'''


def brightness(radius, intensity=1.0):
    scene = Loader.loads(SCENE % (str(radius).encode(), str(intensity).encode()), 'scene.x3d')
    with scene_context(scene, size=(48, 48), environment=COMPATIBILITY) as context:
        drawn_image(context)
        image = drawn_image(context)
    return float(np.asarray(image[16:32, 16:32], dtype=float).mean())


def test_a_wall_past_the_radius_is_unlit(gl_context_compat):
    """Past the radius the wall is as it is under a light of no intensity"""
    unlit = brightness(50.0, intensity=0.0)
    assert brightness(50.0) > unlit + 50
    assert brightness(10.0) == pytest.approx(unlit, abs=1.0)
