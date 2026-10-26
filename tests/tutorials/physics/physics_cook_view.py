#! /usr/bin/env python
'''=Physics: cooking collision shapes from a mesh=

[physics_cook_view.py-screen-0001.png Screenshot]

A boulder drawn as a triangle mesh has no hand-made collider, so the world
cooks one from the triangles the node draws.  The solid mesh is the render
geometry; the green wireframe is the *cooked* collision proxy that
``physics.show_proxies`` overlays on it, so you can see how well the proxy
matches.  Press **c** to cycle the cooking strategy (convex hull, box, sphere)
and watch the proxy change.

Keys:
    c   cycle cooking strategy
    r   reset
'''
import numpy as np

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.scenegraph import natural, surfaces
from OpenGLContext.scenegraph.basenodes import Background, DirectionalLight, sceneGraph

STRATEGIES = ['convex', 'box', 'sphere']


def blob_node(seed=2):
    '''A boulder of grey sandstone, 2.8 m by 2 m by 2 m: a sphere with flat
    faces scraped into it and its surface roughened, from the engine's
    procedural rocks. It is a mesh with no collider of its own.'''
    rock = natural.stone(np.random.default_rng(seed), (1.4, 1.0, 1.0), divisions=2)
    grey = surfaces.pbr_material(surfaces.sandstone(256, colour=(0.52, 0.50, 0.47)),
                                 roughness=0.9)
    return surfaces.shape(rock, grey)


class TestContext(BaseContext):
    initialPosition = (0, 3, 10)

    def OnInit(self):
        self._strategy = 0
        self.build()
        print(__doc__)
        self.addEventHandler('keypress', name='c', function=self.on_cycle)
        self.addEventHandler('keypress', name='r', function=self.on_reset)

    def on_reset(self, event):
        self.build()

    def build(self):
        stone = surfaces.pbr_material(surfaces.sandstone(256))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.62, 0.72)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.0),
            surfaces.shape(surfaces.block((12, 1, 12), repeat=3.0), stone,
                           translation=(0, -0.5, 0)),
        ])
        self.blob = blob_node()
        self.sg.children.append(self.blob)
        strategy = STRATEGIES[self._strategy]
        '''``cook`` makes the proxy from the node's triangles by a strategy:
        ``'convex'`` takes the hull, ``'box'`` and ``'sphere'`` fit that
        primitive to the bounds.  A cooked proxy is a value: it can be given to
        any number of bodies, and the world holds its shape once.'''
        self.proxy = self.physics.cook(self.blob, strategy)
        self.body = self.physics.add_dynamic(
            self.blob, proxy=self.proxy, translation=(0, 4, 0), mass=2.0)
        self.physics.show_proxies(True)
        print('cooking strategy:', strategy)

    def on_cycle(self, event):
        self._strategy = (self._strategy + 1) % len(STRATEGIES)
        self.physics.show_proxies(False)
        self.body.remove()
        self.build()


if __name__ == '__main__':
    TestContext.ContextMainLoop()
