#! /usr/bin/env python
'''=Levels of detail: a hall of orbs=

[lod_hall.py-screen-0001.png Screenshot]

The hall of ``oglc-lod``: two rows of metal orbs on sandstone plinths down a
marble floor, and a few marble columns between them.  Each orb is the same
sphere modelled four times, from 48 sides round its equator to 6, and each is
drawn at the level that suits how much of the window it covers: the near orbs
at their finest, the far ones at their coarsest.
'''
import os

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.bin.lod_demo import LODHall
from OpenGLContext.scenegraph.basenodes import sceneGraph


class TestContext(BaseContext):
    initialPosition = (0.0, 1.6, 4.0)

    def OnInit(self):
        '''The hall builds the scene.  Its ``_orb`` is where a chain is made in
        code: a ``ScreenCoverageLOD`` whose ``level`` holds the four spheres,
        finest first, and whose ``screenCoverage`` gives the share of the
        window's height at which each takes over -- ``0.25``, ``0.12``,
        ``0.05`` and ``0``, the last keeping the coarsest orb on screen however
        far away it is.  ``_from_file`` writes the right-hand row with
        ``GLTFWriter.add_lod``, as ``MSFT_lod`` chains, and reads it back with
        ``load_gltf``, which builds the same node from the file.  The columns
        are VRML97's ``LOD``, chosen by distance, with a ``range`` of 12 and
        24 metres.'''
        self.hall = LODHall()
        self.sg = sceneGraph(children=self.hall.children)
        '''``t`` dresses each level in its own metal -- gold, copper, steel,
        silver -- so the places where the levels change can be seen while
        walking.  ``h`` switches each node's ``hysteresis`` off: a level then
        changes exactly at its threshold rather than a tenth of it beyond,
        and a viewer standing on a threshold sees it flicker.'''
        for key in LODHall.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(LODHall.help())

    def OnKey(self, event):
        said = self.hall.press(event.name)
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
