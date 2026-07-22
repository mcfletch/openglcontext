#! /usr/bin/env python
'''=Physics: objects falling into a room=

[physics_room_drop.py-screen-0001.png Screenshot]

A stack of boxes and spheres falls into a walled room and settles.  It exercises
the whole engine: symplectic-Euler integration, primitive collision, the
sequential-impulse solver, stacking, and sleeping.  The green wireframes are the
collision proxies and the red stubs are contact normals, drawn by the physics
debug overlay.

Keys:
    space  drop another body
    r      reset the scene
    d      cycle debug overlay (proxies / +aabbs / +velocity / all / off)
'''
import time
import numpy as np

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from omi_physics import model
from OpenGLContext.physics.demo import DemoScene, disable_vsync
from OpenGLContext.physics import debugdraw

DEBUG_CYCLE = [
    debugdraw.PROXIES | debugdraw.CONTACTS,
    debugdraw.PROXIES | debugdraw.CONTACTS | debugdraw.AABBS,
    debugdraw.PROXIES | debugdraw.VELOCITY | debugdraw.ACCELERATION | debugdraw.ANGULAR,
    debugdraw.ALL,
    0,
]


class TestContext(BaseContext):
    initialPosition = (0, 7, 18)

    def OnInit(self):
        disable_vsync()
        self.rng = np.random.RandomState(1234)
        self._debug_index = 0
        self.build_scene()
        print(__doc__)
        self.addEventHandler('keypress', name='r', function=self.on_reset)
        self.addEventHandler('keypress', name=' ', function=self.on_add)
        self.addEventHandler('keypress', name='d', function=self.on_debug)
        self._last = time.time()

    def build_scene(self):
        self.scene = DemoScene(debug_flags=DEBUG_CYCLE[self._debug_index])
        room(self.scene)
        for k in range(8):
            self.drop_one(k)
        self.scene.advance(0.0)
        self.sg = self.scene.scene_graph()

    def drop_one(self, k):
        x = self.rng.uniform(-2.5, 2.5)
        z = self.rng.uniform(-2.5, 2.5)
        y = 6.0 + 1.3 * k
        if k % 2:
            self.scene.add_box(size=(1, 1, 1), position=(x, y, z),
                               color=(0.85, 0.75, 0.5), material='wood')
        else:
            self.scene.add_sphere(radius=0.6, position=(x, y, z),
                                  color=(0.4, 0.6, 0.9), material='rubber')

    def OnIdle(self, *args):
        now = time.time()
        dt = min(now - self._last, 0.05)
        self._last = now
        if self.scene.advance(dt):
            self.triggerRedraw(1)
        return 1

    def on_reset(self, event):
        self.build_scene()

    def on_add(self, event):
        self.drop_one(self.rng.randint(0, 100))
        self.sg = self.scene.scene_graph()

    def on_debug(self, event):
        self._debug_index = (self._debug_index + 1) % len(DEBUG_CYCLE)
        self.scene.debug.flags = DEBUG_CYCLE[self._debug_index]


def room(scene, size=6.0, wall=0.4, height=4.0):
    s = size
    scene.add_box(size=(2 * s, 1, 2 * s), position=(0, -0.5, 0),
                  color=(0.5, 0.5, 0.55), dynamic=False)
    for sx, sz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if sx:
            scene.add_box(size=(wall, height, 2 * s), position=(sx * s, height / 2, 0),
                          color=(0.45, 0.45, 0.5), dynamic=False)
        else:
            scene.add_box(size=(2 * s, height, wall), position=(0, height / 2, sz * s),
                          color=(0.45, 0.45, 0.5), dynamic=False)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
