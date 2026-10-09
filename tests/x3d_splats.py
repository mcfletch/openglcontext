#! /usr/bin/env python
'''=X3D: Gaussian splats on a marble terrace=

[x3d_splats.py-screen-0001.png Screenshot]

``oglc-x3d-splats`` opens ``x3d_splats.x3d``, an X3D 4.1 document with two
sets of Gaussian splats in it:

* the brass vase is a ``GaussianSplats`` node in the document: flat splats
  laid over a lathed surface, ``positions``, ``orientations``, ``scales``
  and ``opacities`` one per splat, and spherical harmonics to degree 3 that
  carry how polished brass under this sky looks from every side, so its
  sheen moves as the viewer does;
* the hedge is a glTF file the document ``Inline``s, whose one primitive
  carries ``KHR_gaussian_splatting``: leaves scattered through a rounded
  block, their colour degree 0 alone.

Each set is sorted back to front by distance from the camera and blended
over the meshes around it; both cast shadows on the terrace, from the cores
of their splats. The floor, the sandstone plinth and the steel ball are
meshes.
'''
import os
import tempfile

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.bin.x3d_splats import Showcase
from OpenGLContext.loaders import background


class TestContext(BaseContext):

    def OnInit(self):
        '''The showcase writes the document, the hedge and the maps they name,
        and reads it with ``Loader.load``.'''
        self.showcase = Showcase(tempfile.mkdtemp(prefix='x3d-splats-'))
        background.wait_for_idle(20.0)
        self.sg = self.showcase.scene
        '''``d`` takes the vase's harmonics above degree 0 away and gives them
        back, ``s`` switches the splats' ``castShadow``, ``g`` writes the vase
        as a ``KHR_gaussian_splatting`` glTF, and ``w`` writes the scene back
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
