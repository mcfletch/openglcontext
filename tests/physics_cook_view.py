#! /usr/bin/env python
'''=Physics: cooking collision shapes from a mesh=

[physics_cook_view.py-screen-0001.png Screenshot]

An arbitrary triangle mesh (a lumpy blob) has no hand-made collider, so
``cookery.cook_shape`` derives one.  The solid mesh is the render geometry; the
green wireframe is the *cooked* collision proxy overlaid on top, so you can see
how well the proxy matches.  Press **c** to cycle the cooking strategy
(convex / primitive / decompose) and watch the proxy change.

Keys:
    c   cycle cooking strategy
    r   reset
'''
import time
import numpy as np

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph import basenodes
from omi_physics import model, hull
from OpenGLContext.physics import debugdraw
from omi_physics.cookery import cook_shape
from OpenGLContext.physics.demo import DemoScene, disable_vsync

STRATEGIES = ['convex', 'primitive', 'decompose']


def blob_mesh(seed=2):
    rng = np.random.RandomState(seed)
    pts = rng.normal(size=(40, 3))
    pts /= np.linalg.norm(pts, axis=1, keepdims=True)
    pts *= (0.8 + 0.5 * rng.rand(40, 1)) * np.array([1.4, 1.0, 1.0])
    verts, faces = hull.convex_hull(pts)
    coord = basenodes.Coordinate(point=[tuple(v) for v in verts])
    index = []
    for f in faces:
        index += [int(f[0]), int(f[1]), int(f[2]), -1]
    geom = basenodes.IndexedFaceSet(coord=coord, coordIndex=index, solid=0)
    return geom, verts


class TestContext(BaseContext):
    initialPosition = (0, 3, 10)

    def OnInit(self):
        disable_vsync()
        self._strategy = 0
        self.build()
        print(__doc__)
        self.addEventHandler('keypress', name='c', function=self.on_cycle)
        self.addEventHandler('keypress', name='r', function=self.on_reset)
        self._last = time.time()

    def on_reset(self, event):
        self.build()
        self.triggerRedraw(1)

    def build(self):
        self.scene = DemoScene(debug_flags=debugdraw.PROXIES)
        self.scene.add_box(size=(12, 1, 12), position=(0, -0.5, 0),
                           color=(0.5, 0.5, 0.55), dynamic=False)
        geom, verts = blob_mesh()
        strat = STRATEGIES[self._strategy]
        cooked = cook_shape(verts, strategy=strat, dynamic=True)
        if isinstance(cooked, list):
            cooked = cooked[0]                          # show the first convex piece
        self.scene.add_mesh_body(geom, cooked, position=(0, 4, 0),
                                 color=(0.75, 0.55, 0.4))
        self.scene.advance(0.0)
        self.sg = self.scene.scene_graph()
        print('cooking strategy:', strat)

    def on_cycle(self, event):
        self._strategy = (self._strategy + 1) % len(STRATEGIES)
        self.build()

    def OnIdle(self, *args):
        now = time.time()
        active = self.scene.advance(min(now - self._last, 0.05))
        self._last = now
        if active:
            self.triggerRedraw(1)
        return 1


if __name__ == '__main__':
    TestContext.ContextMainLoop()
