#! /usr/bin/env python
'''=Physics: trigger sensors=

[physics_triggers.py-screen-0001.png Screenshot]

Balls drop through a cyan **trigger** volume.  A trigger detects overlap but
applies no impulse, so the balls fall straight through; each one lights up green
while it is inside the volume and returns to its colour on exit.  Trigger
enter/stay/exit events drive pickups, pressure plates, and region logic.
'''
import time

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from omi_physics import model
from OpenGLContext.physics import debugdraw
from OpenGLContext.physics.demo import DemoScene, disable_vsync


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
        self.scene = DemoScene(debug_flags=debugdraw.PROXIES | debugdraw.CONTACTS)
        self.scene.add_box(size=(20, 1, 6), position=(0, -6, 0),
                           color=(0.5, 0.5, 0.55), dynamic=False)
        self.scene.add_trigger_box(size=(14, 1.5, 4), position=(0, 0, 0))
        self._materials = {}
        for k in range(6):
            body = self.scene.add_sphere(radius=0.5, position=(-6 + k * 2.4, 6, 0),
                                         color=(0.9, 0.6, 0.3))
            self._materials[body.index] = body.transform.children[0].appearance.material
        self.scene.world.add_trigger_listener(self.on_trigger)
        self.scene.advance(0.0)
        self.sg = self.scene.scene_graph()

    def on_trigger(self, kind, trigger, other):
        mat = self._materials.get(other)
        if mat is None:
            return
        if kind == 'enter':
            mat.diffuseColor = (0.2, 1.0, 0.3)
        elif kind == 'exit':
            mat.diffuseColor = (0.9, 0.6, 0.3)

    def OnIdle(self, *args):
        now = time.time()
        active = self.scene.advance(min(now - self._last, 0.05))
        self._last = now
        if active:
            self.triggerRedraw(1)
        return 1


if __name__ == '__main__':
    TestContext.ContextMainLoop()
