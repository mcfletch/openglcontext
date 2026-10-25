#! /usr/bin/env python
'''=X3D: layers, an inset viewport and a panel placed in pixels=

[x3d_layering.py-screen-0001.png Screenshot]

``oglc-x3d-layering`` opens ``x3d_layering.x3d``, an X3D 4 document drawn as
a stack of four layers.  The ``LayerSet`` names the order they are drawn in,
bottom first, and each is drawn over the ones beneath it with the depth
buffer cleared:

* layer 0 is the scene's own children: a courtyard of sandstone, brick,
  marble, copper, steel, brass and wood, which the mouse navigates;
* layer 1 is the same courtyard (a ``USE`` of its group) seen from above
  through the layer's own ``Viewpoint``, confined by its ``Viewport`` to the
  top right of the window;
* layer 2 is a ``LayoutLayer`` whose ``LayoutGroup`` draws a brass plate a
  little larger than the inset, as fractions of the window, under it;
* layer 3 is a ``LayoutLayer`` whose ``Layout`` places a wooden panel 268 by
  84 pixels, 16 pixels in from the bottom left, with text in a
  ``ScreenFontStyle`` and a brass button.

The button's ``TouchSensor`` is routed through a ``BooleanFilter`` and a
``BooleanToggle`` to the ``visible`` field of the inset and its frame.
'''
import os
import tempfile

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.bin.x3d_layering import LayeringScene
from OpenGLContext.loaders import background


class TestContext(BaseContext):

    def OnInit(self):
        '''The showcase copies the document beside the maps it names, and
        reads it with ``Loader.load``.'''
        self.layering = LayeringScene(tempfile.mkdtemp(prefix='x3d-layering-'))
        background.wait_for_idle(20.0)
        self.sg = self.layering.scene
        '''``i`` shows and hides the inset and its frame, as the button does,
        and ``p`` the panel.'''
        for key in LayeringScene.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(LayeringScene.help())

    def OnKey(self, event):
        said = self.layering.press(event.name)
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
