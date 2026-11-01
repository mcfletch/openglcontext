#! /usr/bin/env python
'''=Physics: restitution (bounciness)=

[physics_bounce.py-screen-0001.png Screenshot]

A row of balls dropped from the same height with restitution rising from 0
(dead) on the left to 1 (nearly lossless) on the right.  Watch the rebound
heights increase across the row: a direct read-out of the ``restitution``
keyword of ``add_dynamic``.
'''
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
)
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

BALLS = 6
RADIUS = 0.7


class TestContext(BaseContext):
    initialPosition = (0, 5, 22)

    def OnInit(self):
        self.balls = []
        self.build()
        print(__doc__)
        self.addEventHandler('keypress', name='r', function=self.on_reset)

    def on_reset(self, event):
        self.build()

    def build(self):
        '''A body outlives the scene it was drawn in, so the old balls are
        removed from the world as the new scene is made.  The floor is a shape
        of the scene, so it is static.'''
        for body in self.balls:
            body.remove()
        slab = surfaces.pbr_material(surfaces.sandstone(256))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.62, 0.72)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.0),
            surfaces.shape(surfaces.block((24, 1, 6), repeat=3.0), slab,
                           translation=(0, -0.5, 0)),
        ])
        self.balls = []
        for k in range(BALLS):
            e = k / (BALLS - 1)
            skin = PhysicalMaterial(baseColor=(0.3 + 0.6 * e, 0.5, 0.9 - 0.6 * e),
                                    metallic=0.1, roughness=0.3)
            node = surfaces.shape(surfaces.sphere(RADIUS), skin)
            self.sg.children.append(node)
            '''``restitution`` is the fraction of its closing speed a body
            keeps from a bounce.  It is combined with the floor's, so a ball of
            0 on a floor of 0.2 is nearly dead.'''
            self.balls.append(self.physics.add_dynamic(
                node, translation=(-9 + k * 3.6, 8, 0), restitution=e, friction=0.4))
        self.physics.show_proxies(True)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
