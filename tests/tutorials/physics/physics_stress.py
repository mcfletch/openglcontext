#! /usr/bin/env python
'''=Physics: stress / scaling=

[physics_stress.py-screen-0001.png Screenshot]

A large pile of boxes and spheres drops into a bowl to exercise the broad phase,
islands, and sleeping under load.  Jolt steps the pile on pyjoltphysics' world
thread with its job threads; ``mode='inline'`` runs the world in lockstep with
the frame, so a capture of it is the same on every run.  ``physics.engine``
names the engine, its version and its precision.

Bodies render through the instanced mesh path (all boxes of a size share one GPU
batch), so the render cost stays flat as the pile grows.  The collision-proxy
wireframe overlay is *off* by default -- it rebuilds every body's geometry each
frame and swamps the step at a few hundred bodies; pass ``--debug`` only when you
actually need to see the proxies.

Usage:
    oglc-test tests/tutorials/physics/physics_stress.py [--waves N] [--debug]

Keys:
    space  add another wave of bodies
    r      reset
'''
import numpy as np

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Shape, Sphere, Transform, sceneGraph,
)
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

WAVE = 40


class TestContext(BaseContext):
    initialPosition = (0, 12, 26)
    initial_waves = 1               # --waves N: pre-populate N waves at startup
    show_overlay = False            # --debug: draw the (expensive) proxy overlay
    contextDefinition = ContextDefinition(physics=PhysicsDefinition(mode='inline'))

    def OnInit(self):
        self.rng = np.random.RandomState(7)
        '''Every body of a kind shares one geometry node and one appearance,
        which is what lets the renderer draw them as one batch.'''
        self.cube = Box(size=(1, 1, 1))
        self.ball = Sphere(radius=0.6)
        self.wood = Appearance(material=PhysicalMaterial(
            baseColor=(0.8, 0.7, 0.4), metallic=0.0, roughness=0.6))
        self.steel = Appearance(material=PhysicalMaterial(
            baseColor=(0.4, 0.6, 0.9), metallic=0.4, roughness=0.3))
        self.bodies = []
        self.build()
        print(__doc__)
        # Pass bound methods, not lambdas: the event system holds handlers
        # weakly, so a lambda with no other reference is collected and never fires.
        self.addEventHandler('keypress', name='r', function=self.on_reset)
        self.addEventHandler('keypress', name=' ', function=self.on_add_wave)
        print('physics:', self.physics.engine, flush=True)

    def on_reset(self, event):
        for body in self.bodies:
            body.remove()
        self.bodies = []
        self.build()

    def on_add_wave(self, event):
        self.add_wave()

    def build(self):
        '''A shallow bowl: a floor and four walls, shapes of the scene and so
        static bodies.'''
        stone = surfaces.pbr_material(surfaces.sandstone(256))
        parts = [surfaces.shape(surfaces.block((24, 1, 24), repeat=4.0), stone,
                                translation=(0, -0.5, 0))]
        for sx, sz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            size = (0.5, 5, 24) if sx else (24, 5, 0.5)
            parts.append(surfaces.shape(surfaces.block(size), stone,
                                        translation=(sx * 12, 2.5, sz * 12)))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.62, 0.72)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.0),
            *parts,
        ])
        self.physics.show_proxies(self.show_overlay)
        for _ in range(max(1, self.initial_waves)):
            self.add_wave()

    def add_wave(self):
        for _ in range(WAVE):
            x, z = self.rng.uniform(-9, 9, 2)
            y = self.rng.uniform(8, 18)
            if self.rng.rand() < 0.5:
                geometry, look = self.cube, self.wood
            else:
                geometry, look = self.ball, self.steel
            node = Transform(translation=(x, y, z), children=[
                Shape(geometry=geometry, appearance=look)])
            self.sg.children.append(node)
            self.bodies.append(self.physics.add_dynamic(
                node, proxy='box' if geometry is self.cube else 'sphere'))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Physics stress / scaling demo')
    parser.add_argument('--waves', type=int, default=1,
                        help='number of 40-body waves to drop at startup')
    parser.add_argument('--debug', action='store_true',
                        help='draw the collision-proxy wireframe overlay (slow)')
    args, _ = parser.parse_known_args()
    TestContext.initial_waves = args.waves
    TestContext.show_overlay = args.debug
    TestContext.ContextMainLoop()
