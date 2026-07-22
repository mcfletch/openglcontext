#! /usr/bin/env python
'''=Physics: restitution (bounciness)=

[physics_bounce.py-screen-0001.png Screenshot]

A row of balls dropped from the same height with restitution rising from 0
(dead) on the left to 1 (nearly lossless) on the right.  Watch the rebound
heights increase across the row — a direct read-out of the ``restitution``
material property and its combine mode.
'''
import time

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from omi_physics import model
from OpenGLContext.physics import debugdraw
from OpenGLContext.physics.demo import DemoScene, disable_vsync


class TestContext(BaseContext):
    initialPosition = (0, 4, 16)

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
        self.scene = DemoScene(debug_flags=debugdraw.PROXIES)
        self.scene.add_box(size=(24, 1, 6), position=(0, -0.5, 0),
                           color=(0.5, 0.5, 0.55), dynamic=False, material='wood')
        n = 6
        for k in range(n):
            e = k / (n - 1)
            mat = self.scene.raw_material(model.Material(
                restitution=e, staticFriction=0.4, dynamicFriction=0.4))
            self.scene.add_sphere(radius=0.7, position=(-9 + k * 3.6, 8, 0),
                                  color=(0.3 + 0.6 * e, 0.5, 0.9 - 0.6 * e),
                                  material=mat)
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
