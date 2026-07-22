#! /usr/bin/env python
'''=Physics: joints (OMI_physics_joint)=

[physics_joints.py-screen-0001.png Screenshot]

A pendulum and a hanging chain, each built from ``DistanceConstraint`` links to a
fixed anchor, plus a motorised spinner driven by an ``AngularMotor``.  The yellow
lines are the joint connections drawn by the debug overlay.  Joints are solved as
velocity constraints alongside contacts.
'''
import time
import numpy as np

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from omi_physics import model
from OpenGLContext.physics import debugdraw
from OpenGLContext.physics.demo import DemoScene, disable_vsync
from omi_physics.joints import DistanceConstraint, AngularMotor


class TestContext(BaseContext):
    initialPosition = (0, 3, 16)

    def OnInit(self):
        disable_vsync()
        self.build()
        print(__doc__)
        self.addEventHandler('keypress', name='r', function=self.on_reset)
        self._last = time.time()

    def on_reset(self, event):
        self.build()
        self.triggerRedraw(1)

    def build(self):
        self.scene = DemoScene(debug_flags=debugdraw.PROXIES | debugdraw.JOINTS)
        w = self.scene.world

        # pendulum: a bob on a 2 m arm from a fixed pivot
        pivot = (-5.0, 6.0, 0.0)
        bob = self.scene.add_sphere(radius=0.5, position=(-3.0, 6.0, 0.0),
                                    color=(0.9, 0.4, 0.3))
        w.add_joint_constraint(DistanceConstraint(
            -1, bob.index, anchor_a=pivot, anchor_b=(0, 0, 0), length=2.0))

        # chain: a column of links, each held a fixed distance below the previous
        prev, prev_pos = -1, np.array([2.0, 7.0, 0.0])
        for k in range(5):
            pos = prev_pos - (0, 1.0, 0)
            link = self.scene.add_box(size=(0.6, 0.6, 0.6), position=tuple(pos),
                                      color=(0.5, 0.7, 0.9))
            anchor_a = (0, 0, 0) if prev >= 0 else tuple(prev_pos)
            w.add_joint_constraint(DistanceConstraint(
                prev, link.index, anchor_a=anchor_a, anchor_b=(0, 0, 0), length=1.0))
            prev, prev_pos = link.index, pos

        # motorised spinner
        spinner = self.scene.add_box(size=(3, 0.3, 0.3), position=(6, 4, 0),
                                     color=(0.9, 0.8, 0.3))
        w.add_joint_constraint(AngularMotor(spinner.index, axis=(0, 1, 0),
                                            target=4.0, max_force=30.0))
        self.scene.advance(0.0)
        self.sg = self.scene.scene_graph()

    def OnIdle(self, *args):
        now = time.time()
        active = self.scene.advance(min(now - self._last, 0.05))
        self._last = now
        if active:
            self.triggerRedraw(1)
        return 1


if __name__ == '__main__':
    TestContext.ContextMainLoop()
