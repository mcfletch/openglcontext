#! /usr/bin/env python
"""Spot-light shadow-mapping test scene.

A grey wall faces the default camera (looking down -Z from z=10). A red occluder
box floats in front of the wall, lit by a single spot light off to the
upper-right. With shadow mapping enabled (OPENGLCONTEXT_SHADOWS=1, core profile)
the box casts a dark shadow onto the wall, offset toward the lower-left of the
box so the shadow and the box occupy separate, easily analysed image regions.

Run standalone to view interactively. The shadow regression test
(tests/test_shadow_rendering.py) renders this scene off-screen with and without
shadows and compares the results.
"""
import os

# Shadow mapping needs the core-profile shader path with shadows enabled. Set
# these before importing OpenGLContext so a plain ``python shadow_spot.py`` shows
# the shadow. Override any of them in the environment (e.g. OPENGLCONTEXT_SHADOWS=0
# to see the scene without shadows, OPENGLCONTEXT_SHADOWS_SOFT=1 for soft shadows).
os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '1')

from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph import basenodes


def _light(kind):
    if kind == 'directional':
        return basenodes.DirectionalLight(
            direction=(-0.7, -0.7, -1.0),
            color=(1, 1, 1), intensity=1.0, ambientIntensity=0.3,
        )
    if kind == 'point':
        return basenodes.PointLight(
            location=(5, 5, 6),
            color=(1, 1, 1), intensity=1.0, ambientIntensity=0.3,
            attenuation=(1, 0, 0),
        )
    return basenodes.SpotLight(
        location=(7, 7, 7),
        direction=(-9, -9, -13),
        cutOffAngle=0.9,
        color=(1, 1, 1), intensity=1.0, ambientIntensity=0.3,
        attenuation=(1, 0, 0),
    )


def make_scene(light='spot'):
    """Build the shadow test scenegraph (default -Z camera).

    light -- 'spot', 'directional', or 'point' (the shadow-casting light kind).
    """
    return basenodes.sceneGraph(
        children=[
            # Grey wall receiver behind the occluder, facing the camera (+Z normal)
            basenodes.Transform(
                translation=(0, 0, -6),
                children=[
                    basenodes.Shape(
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(
                                diffuseColor=(0.75, 0.75, 0.75),
                                ambientIntensity=0.3,
                            ),
                        ),
                        geometry=basenodes.Box(size=(30, 30, 0.3)),
                    ),
                ],
            ),
            # Red occluder box between camera and wall, offset up-right
            basenodes.Transform(
                translation=(1.5, 1.5, 0),
                children=[
                    basenodes.Shape(
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(
                                diffuseColor=(0.9, 0.1, 0.1),
                                ambientIntensity=0.3,
                            ),
                        ),
                        geometry=basenodes.Box(size=(2, 2, 2)),
                    ),
                ],
            ),
            # Shadow-casting light up and to the right, so the box shadow is cast
            # toward the lower-left of the wall.
            _light(light),
        ],
    )


class TestContext(BaseContext):
    def OnInit(self):
        import os
        self.sg = make_scene(os.environ.get('SHADOW_LIGHT', 'spot'))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
