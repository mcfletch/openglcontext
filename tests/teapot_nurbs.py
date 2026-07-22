#! /usr/bin/env python
"""Display the glut-free NURBS-tessellated Utah Teapot.

Renders three teapots: a full teapot, a lid-less teapot (``lid=False``), and
a wireframe teapot, all generated from the Newell Bezier patches via the GLU
NURBS tessellators rather than the GLUT endpoint.

The Utah Teapot was modelled by Martin Newell in 1975 at the University of
Utah.  See https://graphics.cs.utah.edu/teapot/.
"""
import os

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive('glfw')

from OpenGLContext.scenegraph import basenodes


def _teapot_shape(position, diffuse, lid=True, solid=True):
    return basenodes.Transform(
        translation=position,
        children=[
            basenodes.Shape(
                geometry=basenodes.Teapot(
                    size=1.0, solid=solid, lid=lid,
                ),
                appearance=basenodes.Appearance(
                    material=basenodes.Material(
                        diffuseColor=diffuse,
                        specularColor=(1, 1, 1),
                        shininess=0.7,
                    ),
                ),
            ),
        ],
    )


class TestContext(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.DirectionalLight(
                    direction=(0.5, -1, -0.5), color=(1, 1, 1), intensity=1.0,
                ),
                _teapot_shape((-2.6, 0, 0), (0.7, 0.3, 0.2), lid=True),
                _teapot_shape((0, 0, 0), (0.3, 0.6, 0.3), lid=False),
                _teapot_shape((2.6, 0, 0), (0.3, 0.4, 0.7), solid=False),
                basenodes.Background(skyColor=[(0.2, 0.2, 0.3)]),
            ],
        )
        self.platform = self.getViewPlatform()
        self.platform.setPosition((0, 1.0, 7))
        self.platform.setOrientation((1, 0, 0, -0.12))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
