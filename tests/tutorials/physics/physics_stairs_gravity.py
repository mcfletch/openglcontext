#! /usr/bin/env python
'''=Physics: a gravity zone=

[physics_stairs_gravity.py-screen-0001.png Screenshot]

Gravity is 9.81 m/s squared downward everywhere until a zone changes it. A
zone is a region of space with a gravity of its own, and a body inside it is
pulled by the zone's gravity added to the world's. A column of rising air at
the foot of the stairs lifts the ball of :doc:`physics_stairs` and drops it
again at the top.
'''
from physics_stairs import TestContext as Rolling
from OpenGLContext.physics.zones import Box
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box as BoxGeometry, Material, Shape, Transform,
)

#: The column of air: where it is and how big, in metres.
CENTRE = (0, 2.0, 3.0)
SIZE = (3, 4, 2)


class TestContext(Rolling):
    def OnInit(self):
        super().OnInit()
        '''``Box`` is a region of ``size`` metres around ``center``; ``Sphere``
        is the other region. ``gravity`` is an acceleration in metres a second
        squared: a vector, or one number for downward. The zone's 14 m/s
        squared upward and the world's 9.81 downward leave 4.2 m/s squared up
        inside it, and nothing outside it.'''
        self.zone = self.physics.add_gravity_zone(
            Box(center=CENTRE, size=SIZE), gravity=(0, 14, 0))
        '''A zone is not drawn. A translucent box of the same size marks it.'''
        self.sg.children.append(Transform(translation=CENTRE, children=[Shape(
            geometry=BoxGeometry(size=SIZE),
            appearance=Appearance(material=Material(
                diffuseColor=(0.4, 0.7, 1.0), transparency=0.8)))]))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
