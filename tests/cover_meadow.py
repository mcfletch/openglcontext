#! /usr/bin/env python
'''=Ground cover: a meadow and a well=

[cover_meadow.py-screen-0001.png Screenshot]

The meadow of ``oglc-cover``: grass, ferns and flowers over low hills, rock on
the ridge to the north, and a stone well cut into the ground.  The terrain is
a ``SplatTerrain`` over a ``HeightField``; the plants are one ``GroundCover``
of three ``CoverSpecies``, scattered around the camera as it moves.
'''
import os

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.bin.cover_demo import Meadow
from OpenGLContext.scenegraph.basenodes import sceneGraph


class TestContext(BaseContext):
    def OnInit(self):
        '''The meadow builds the land, its splat control map, the terrain and
        the cover.  ``control_map`` paints meadow everywhere, earth where the
        ground steepens and rock on the ridge, from ``LayerRule`` bands of
        slope; ``control_weight`` turns the meadow layer into the mask the
        cover grows on, so nothing grows on the rock.  Each ``CoverSpecies``
        names its card and how it gathers: the grass also names a clump, a
        ``.glb`` with a fuller mesh (``near``) and a coarser one (``far``)
        for the geometry drawn close in; the ferns' ``patchiness`` of 0.85
        and ``patchMetres`` of 18 put them in beds.  The cover is scattered in
        line here, ``background=False``, so the first frame drawn has all of
        it; the demo scatters on a worker thread.'''
        self.meadow = Meadow(background=False)
        position, orientation = self.meadow.viewpoint()
        self.getViewPlatform().setPosition(position)
        self.getViewPlatform().setOrientation(orientation)
        self.sg = sceneGraph(children=self.meadow.children)
        '''The well is ``holes``: one callable, given to the terrain and to
        the cover, true over the well's mouth.  The terrain cuts its mesh
        along the edge of the opening, and nothing is scattered over it.
        ``o`` closes and opens it; ``d`` steps the cover's ``density_scale``
        through all, half and none.'''
        for key in Meadow.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(Meadow.help())

    def OnDraw(self, *args, **named):
        self.meadow.update(self.getViewPlatform().position)
        return super().OnDraw(*args, **named)

    def OnKey(self, event):
        said = self.meadow.press(event.name)
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
