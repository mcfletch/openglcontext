#! /usr/bin/env python
'''=Physics: Coulomb friction on ramps=

[physics_friction.py-screen-0001.png Screenshot]

Identical boxes are placed on ramps of increasing angle.  A box slides only when
``tan(angle) > friction``, so the shallow ramps hold their box and the steep ones
let it slide — the classic friction-cone threshold, with the material's
``staticFriction`` / ``dynamicFriction`` and combine mode doing the work.
'''
import time
import numpy as np

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from omi_physics import model, mathutil
from OpenGLContext.physics import debugdraw
from OpenGLContext.physics.demo import DemoScene, disable_vsync


class TestContext(BaseContext):
    initialPosition = (0, 5, 20)

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
        self.scene = DemoScene(debug_flags=debugdraw.PROXIES | debugdraw.VELOCITY)
        mat = self.scene.raw_material(model.Material(
            staticFriction=0.5, dynamicFriction=0.5))
        for k, deg in enumerate((10, 25, 40)):
            x = -8 + k * 8
            self._ramp(x, deg, mat)
        self.scene.advance(0.0)
        self.sg = self.scene.scene_graph()

    def _ramp(self, x, deg, mat):
        angle = np.radians(deg)
        axis_angle = (0, 0, 1, angle)
        self.scene.add_box(size=(6, 0.4, 4), position=(x, 1.5, 0),
                           color=(0.45, 0.45, 0.5), dynamic=False,
                           material=mat, rotation=axis_angle)
        # seat a box on the ramp surface, aligned to the slope
        up = mathutil.quat_rotate(mathutil.quat_from_axis_angle((0, 0, 1), angle),
                                  np.array([0.0, 1.0, 0.0]))
        pos = np.array([x, 1.5, 0]) + up * 0.5
        self.scene.add_box(size=(0.8, 0.8, 0.8), position=tuple(pos),
                           color=(0.9, 0.7, 0.3), material=mat, rotation=axis_angle)

    def OnIdle(self, *args):
        now = time.time()
        active = self.scene.advance(min(now - self._last, 0.05))
        self._last = now
        if active:
            self.triggerRedraw(1)
        return 1


if __name__ == '__main__':
    TestContext.ContextMainLoop()
