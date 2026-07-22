#! /usr/bin/env python
'''=Physics: gravity zones (OMI_physics_gravity)=

[physics_gravity_zones.py-screen-0001.png Screenshot]

A central "planet" carries a **point** gravity volume: loose debris scattered
around it falls *inward* toward the centre instead of straight down, because the
volume replaces the global gravity within its radius.  This is the
``OMI_physics_gravity`` volume resolved by priority/replace.
'''
import time
import numpy as np

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from omi_physics import model
from OpenGLContext.physics import debugdraw
from OpenGLContext.physics.demo import DemoScene, disable_vsync
from omi_physics.gravity import SphereRegion


class TestContext(BaseContext):
    initialPosition = (0, 6, 22)

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
        self.scene = DemoScene(gravity=model.Gravity(gravity=0.0),
                               debug_flags=debugdraw.PROXIES | debugdraw.ACCELERATION)
        self.scene.add_gravity_volume(
            model.Gravity(type=model.POINT, gravity=12.0, center=(0, 0, 0),
                          priority=5, replace=True),
            SphereRegion((0, 0, 0), 30.0))
        self.scene.add_sphere(radius=1.6, position=(0, 0, 0), color=(0.4, 0.7, 1.0),
                              dynamic=False)                 # the planet
        rng = np.random.RandomState(3)
        for _ in range(14):
            d = rng.normal(size=3)
            d /= np.linalg.norm(d)
            pos = d * rng.uniform(6, 9)
            self.scene.add_box(size=(0.7, 0.7, 0.7), position=tuple(pos),
                               color=(0.8, 0.6, 0.4))
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
