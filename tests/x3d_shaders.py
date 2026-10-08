#! /usr/bin/env python
'''=X3D: shapes drawn by their own shaders=

[x3d_shaders.py-screen-0001.png Screenshot]

``oglc-x3d-shaders`` opens ``x3d_shaders.x3d``, an X3D 4 document whose
shapes are drawn by GLSL the document carries.  Each `Appearance` lists a
shader in its ``shaders`` field, and the engine draws the shape with the
first one that is GLSL and links:

* the copper sphere is a ``ComposedShader`` of two ``ShaderPart`` nodes,
  reading the sun through ``x3d_LightSource[0]`` and its colour through
  ``x3d_Material``; the number of bands is a field the document declares,
  which is the uniform of the same name;
* the marble column is a ``ProgramShader`` written in GLSL 1.20 --
  ``ftransform()``, ``gl_LightSource[0]``, ``texture2D`` -- which the engine
  translates for a 3.30 core context; its marble is a texture field;
* the gold sphere comes apart in a ``GEOMETRY`` stage by a ``fraction``
  field the clock is routed to;
* the striped block is a ``PackagedShader``: one file holding both stages;
* the bar is coloured by a ``FloatVertexAttribute``, ``heat``, one value a
  point, which the vertex stage reads as ``in float heat``;
* the pool's vertex stage moves its surface in rings.
'''
import os
import tempfile

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.bin.x3d_shaders_demo import Showcase
from OpenGLContext.loaders import background


class TestContext(BaseContext):

    def OnInit(self):
        '''The showcase copies the document beside the marble map and the
        packaged shader it names, and reads it with ``Loader.load``.'''
        self.showcase = Showcase(tempfile.mkdtemp(prefix='x3d-shaders-'))
        background.wait_for_idle(20.0)
        self.sg = self.showcase.scene
        '''``b`` steps the copper sphere's bands, ``a`` sends every shader
        ``activate``, which links it again, and ``w`` writes the scene back
        as X3D in each encoding.'''
        for key in Showcase.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(Showcase.help())

    def OnKey(self, event):
        said = self.showcase.press(event.name)
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
