#! /usr/bin/env python
"""Utah Teapot with a ceramic PBR material, evoking a traditional teapot.

Demonstrates a physically-based (metallic/roughness) material applied to a
non-glTF geometry -- the ``Teapot`` node -- using the injective texture
coordinates the teapot tessellator now produces.  The material is a pale
celadon glaze with subtle blemishes and a shallow *arare* (hailstone) relief in
the bump map.

This is the first PBR material applied to a hand-built (non-glTF) scenegraph
Shape.  PBR rendering is selected by the two environment variables set below;
the teapot's ``Appearance.material`` simply holds a ``PBRMaterial``, exactly as
a glTF-loaded Shape would.

Rotate/zoom with the mouse; the teapot also spins slowly so the glaze specular
plays across the surface.  Run with the lid off to see the textured interior::

    python tests/teapot_ceramic.py
"""
import os

# PBR pass selection is a whole-process decision (see passes/renderpass.py); it
# must be set before the first render.  glfw is required for a core context.
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive('glfw')

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
from _ceramic_textures import ceramic_textures

# Whether to render the lid (set TEAPOT_LID=0 to open the pot and see inside).
SHOW_LID = os.environ.get('TEAPOT_LID', '1') not in ('0', 'false', 'no')


def ceramic_material(size=1024):
    """Build a celadon-glaze PBRMaterial from the procedural texture set."""
    tex = ceramic_textures(size)
    return PBRMaterial(
        baseColor=(1, 1, 1), metallic=0.0, roughness=1.0, normalScale=1.0,
        textures={
            'baseColor': PBRTexture(tex['baseColor'], srgb=True),
            'metallicRoughness': PBRTexture(tex['metallicRoughness'], srgb=False),
            'normal': PBRTexture(tex['normal'], srgb=False),
        },
    )


class TestContext(BaseContext):
    def OnInit(self):
        spin = basenodes.Transform(rotation=(0, 1, 0, 0), children=[
            basenodes.Shape(
                geometry=basenodes.Teapot(size=1.0, lid=SHOW_LID),
                appearance=basenodes.Appearance(material=ceramic_material()),
            ),
        ])
        timer = basenodes.TimeSensor(cycleInterval=24.0, loop=True)
        turn = basenodes.OrientationInterpolator(
            key=[0.0, 0.25, 0.5, 0.75, 1.0],
            keyValue=[(0, 1, 0, 0), (0, 1, 0, 1.5708), (0, 1, 0, 3.1416),
                      (0, 1, 0, 4.7124), (0, 1, 0, 6.2832)],
        )
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.DirectionalLight(
                    direction=(0.4, -0.8, -0.5), color=(1.0, 0.98, 0.94),
                    intensity=2.2),
                basenodes.DirectionalLight(
                    direction=(-0.6, 0.3, 0.4), color=(0.5, 0.55, 0.7),
                    intensity=0.8),
                spin, timer, turn,
                basenodes.Background(skyColor=[(0.12, 0.13, 0.16)]),
            ],
            routes=[
                (timer, 'fraction_changed', turn, 'set_fraction'),
                (turn, 'value_changed', spin, 'set_rotation'),
            ],
        )
        self.platform = self.getViewPlatform()
        self.platform.setPosition((0, 1.1, 5.2))
        self.platform.setOrientation((1, 0, 0, -0.22))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
