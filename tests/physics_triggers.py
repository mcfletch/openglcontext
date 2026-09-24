#! /usr/bin/env python
'''=Physics: trigger sensors=

[physics_triggers.py-screen-0001.png Screenshot]

Balls drop through a cyan **trigger** volume.  A trigger detects overlap but
applies no impulse, so the balls fall straight through; each one lights up green
while it is inside the volume and returns to its colour on exit.  Trigger
enter/stay/exit events drive pickups, pressure plates, and region logic.

The demo subscribes to the trigger's events through the physics manager, and
each event arrives with the scenegraph node of the ball that entered or left.
'''
import time

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from omi_physics import model
from OpenGLContext.physics import debugdraw
from OpenGLContext.physics.demo import DemoScene, disable_vsync


ORANGE = (0.9, 0.6, 0.3)
GREEN = (0.2, 1.0, 0.3)


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
        zone = self.scene.add_trigger_box(size=(14, 1.5, 4), position=(0, 0, 0))
        for k in range(6):
            self.scene.add_sphere(radius=0.5, position=(-6 + k * 2.4, 6, 0),
                                  color=ORANGE)
        '''The trigger's subscription asks for its ``enter`` and ``exit`` events.
        The manager delivers them from ``advance``, once a frame, after it has
        moved the balls.'''
        self.scene.manager.events.subscribe(
            self.on_trigger, body=zone, kinds=('trigger',), phases=('enter', 'exit'))
        self.scene.advance(0.0)
        self.sg = self.scene.scene_graph()

    def on_trigger(self, hit):
        '''``hit.other_node`` is the ``Transform`` of the ball that entered or left.'''
        material = hit.other_node.children[0].appearance.material
        material.diffuseColor = GREEN if hit.phase == 'enter' else ORANGE

    def OnIdle(self, *args):
        now = time.time()
        active = self.scene.advance(min(now - self._last, 0.05))
        self._last = now
        if active:
            self.triggerRedraw(1)
        return 1


if __name__ == '__main__':
    TestContext.ContextMainLoop()
