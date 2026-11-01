#! /usr/bin/env python
'''=Physics: trigger sensors=

[physics_triggers.py-screen-0001.png Screenshot]

Balls drop through a cyan **trigger** volume.  A trigger detects overlap but
applies no impulse, so the balls fall straight through; each one lights up green
while it is inside the volume and returns to its colour on exit.  Trigger
``enter`` and ``exit`` events drive pickups, pressure plates, and region logic.

The script registers its handlers on the trigger's body, and each event arrives
with the body of the ball that entered or left.
'''
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, Transform, sceneGraph,
)
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

ORANGE = (0.9, 0.6, 0.3)
GREEN = (0.2, 1.0, 0.3)


class TestContext(BaseContext):
    initialPosition = (0, 3, 16)

    def OnInit(self):
        self.balls = []
        self.trigger = None
        self.build()
        print(__doc__)
        self.addEventHandler('keypress', name='r', function=self.on_reset)

    def on_reset(self, event):
        self.build()

    def build(self):
        for body in self.balls:
            body.remove()
        if self.trigger is not None:
            self.trigger.remove()
        floor = surfaces.pbr_material(surfaces.sandstone(256))
        glass = PhysicalMaterial(baseColor=(0.2, 0.9, 0.9), metallic=0.0, roughness=0.1,
                                 transparency=0.75)
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.62, 0.72)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.0),
            surfaces.shape(surfaces.block((20, 1, 6), repeat=3.0), floor,
                           translation=(0, -6.5, 0)),
        ])
        '''A trigger is a body for a node that is drawn or not.  This one
        is drawn as a translucent box, and ``add_trigger`` gives it the shape
        of that box.'''
        zone = surfaces.shape(surfaces.block((14, 1.5, 4)), glass)
        self.sg.children.append(zone)
        self.trigger = self.physics.add_trigger(zone, proxy=Proxy.box((14, 1.5, 4)))
        self.balls = []
        for k in range(6):
            skin = PhysicalMaterial(baseColor=ORANGE, metallic=0.3, roughness=0.35)
            ball = surfaces.shape(surfaces.sphere(0.5), skin)
            self.sg.children.append(ball)
            self.balls.append(self.physics.add_dynamic(ball, translation=(-6 + k * 2.4, 6, 0)))
        '''``'enter'`` and ``'exit'`` are the events of a trigger.  Both are
        delivered to the handler once a frame, after the bodies have moved.'''
        self.trigger.addEventHandler('enter', function=self.on_enter)
        self.trigger.addEventHandler('exit', function=self.on_exit)
        self.physics.show_proxies(True)

    def on_enter(self, hit):
        '''``hit.other`` is the body that entered and ``hit.other_node`` its
        node, whose material the handler changes.'''
        hit.other_node.children[0].appearance.material.baseColor = GREEN

    def on_exit(self, hit):
        hit.other_node.children[0].appearance.material.baseColor = ORANGE


if __name__ == '__main__':
    TestContext.ContextMainLoop()
