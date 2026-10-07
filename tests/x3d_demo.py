#! /usr/bin/env python
'''=X3D: a gallery read from a document=

[x3d_demo.py-screen-0001.png Screenshot]

The gallery of ``oglc-x3d`` is an X3D 4 document, ``x3d_gallery.x3d``, read
by the engine's loader.  Its floor and back wall are ``IndexedTriangleSet``
and ``IndexedTriangleStripSet`` nodes wearing ``PhysicalMaterial`` marble and
brick, whose maps are ``ImageTexture`` nodes the document names by URL; the
spheres are gold, copper and steel ``PhysicalMaterial`` metals on sandstone
plinths drawn with an X3D 4 ``Material`` and its ``diffuseTexture``.  The sun
is a global ``DirectionalLight`` with ``shadows`` true; the alcove's lamp is
a ``DirectionalLight`` with ``global`` false, so it lights only the bronze
ball beside it.  The vase is a glTF model the document ``Inline``s.
'''
import os
import tempfile

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.bin.x3d_demo import Gallery
from OpenGLContext.loaders import background


class TestContext(BaseContext):

    def OnInit(self):
        '''The gallery copies the document into a directory with the textures
        and the vase it names, and reads it with ``Loader.load``: the scene is
        the document's own ``X3DScene``, with its viewpoints and lights.'''
        self.gallery = Gallery(tempfile.mkdtemp(prefix='x3d-gallery-'))
        background.wait_for_idle(20.0)
        self.sg = self.gallery.scene
        '''``l`` turns the alcove's lamp off and on; ``m`` sets the
        medallion's ``visible`` false and true; ``w`` writes the scene back as
        X3D in each encoding beside the document.'''
        for key in Gallery.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(Gallery.help())

    def OnKey(self, event):
        said = self.gallery.press(event.name)
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
