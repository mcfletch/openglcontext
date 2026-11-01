#! /usr/bin/env python
'''=Physics: Coulomb friction on ramps=

[physics_friction.py-screen-0001.png Screenshot]

Identical boxes are placed on ramps of increasing angle.  A box slides only when
``tan(angle) > friction``, so the shallow ramps hold their box and the steep ones
let it slide: the classic friction-cone threshold.  The ``friction`` keyword
sets the coefficient of each surface, and where two meet the world combines
them.
'''
import numpy as np

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
)

#: The coefficient of friction of the ramps and of the boxes, and the angles
#: of the three ramps, in degrees.  tan(25 degrees) is 0.47 and tan(40) is 0.84.
FRICTION = 0.5
ANGLES = (10, 25, 40)


class TestContext(BaseContext):
    initialPosition = (0, 5, 24)

    def OnInit(self):
        self.bodies = []
        self.build()
        print(__doc__)
        self.addEventHandler('keypress', name='r', function=self.on_reset)

    def on_reset(self, event):
        self.build()

    def build(self):
        self.stone = surfaces.pbr_material(surfaces.sandstone(256))
        self.metal = surfaces.pbr_material(surfaces.brushed_metal(256, surfaces.BRONZE))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.62, 0.72)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.0),
        ])
        for body in self.bodies:
            body.remove()
        self.bodies = []
        self.boxes = []
        for k, degrees in enumerate(ANGLES):
            self.ramp(-8 + k * 8, degrees)
        self.physics.show_proxies(True)

    def ramp(self, x, degrees):
        '''A ramp is a static box turned about Z: ``rotation`` is an axis and
        an angle in radians, and is set on the node with the call.  Its
        proxy is a ``'box'``: the exact shape of the ramp, and the cheapest.
        The box stands on its surface, turned the same way.'''
        angle = np.radians(degrees)
        turned = (0, 0, 1, angle)
        ramp = surfaces.shape(surfaces.block((6, 0.4, 4)), self.stone)
        self.sg.children.append(ramp)
        self.bodies.append(self.physics.add_static(
            ramp, proxy='box', translation=(x, 1.5, 0), rotation=turned, friction=FRICTION))
        up = np.array([-np.sin(angle), np.cos(angle), 0.0])
        on = np.array([x, 1.5, 0.0]) + up * 0.61
        box = surfaces.shape(surfaces.block((0.8, 0.8, 0.8)), self.metal)
        self.sg.children.append(box)
        self.boxes.append(self.physics.add_dynamic(
            box, proxy='box', translation=tuple(on), rotation=turned, friction=FRICTION))
        self.bodies.extend((self.boxes[-1],))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
