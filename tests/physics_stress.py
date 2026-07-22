#! /usr/bin/env python
'''=Physics: stress / scaling=

[physics_stress.py-screen-0001.png Screenshot]

A large pile of boxes and spheres drops into a bowl to exercise the broad phase,
islands, and sleeping under load.  The SoA world runs the per-body integration on
numpy for small scenes and hands off to the GPU compute backend past ~10k awake
bodies (``gpu_threshold``); press ``b`` to switch backends live and watch the step
time change (the GPU win is largest for big collider-free swarms).

Bodies render through the instanced mesh path (all boxes of a size share one GPU
batch), so the render cost stays flat as the pile grows.  The collision-proxy
wireframe overlay is *off* by default -- it rebuilds every body's geometry each
frame and swamps the step at a few hundred bodies; pass ``--debug`` only when you
actually need to see the proxies.

Usage:
    oglc-test tests/physics_stress.py [--waves N] [--debug]

Keys:
    space  add another wave of bodies
    b      toggle GPU / numpy physics backend
    r      reset
'''
import sys
import time
import numpy as np

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from omi_physics import model
from OpenGLContext.physics import debugdraw
from omi_physics.backend import select_backend, NumpyBackend
from OpenGLContext.physics.demo import DemoScene, disable_vsync

WAVE = 40


class TestContext(BaseContext):
    initialPosition = (0, 12, 26)
    initial_waves = 1               # --waves N: pre-populate N waves at startup
    debug_flags = 0                 # --debug: enable the (expensive) proxy overlay

    def OnInit(self):
        disable_vsync()
        self.rng = np.random.RandomState(7)
        self.build()
        print(__doc__)
        # NB: pass bound methods, not lambdas -- the event system holds handlers
        # weakly, so a lambda with no other reference is collected and never fires.
        self.addEventHandler('keypress', name='r', function=self.on_reset)
        self.addEventHandler('keypress', name=' ', function=self.on_add_wave)
        self.addEventHandler('keypress', name='b', function=self.on_toggle_backend)
        print('physics backend:', self.scene.world.backend.name, flush=True)
        self._last = time.time()

    def on_reset(self, event):
        self.build()
        self.triggerRedraw(1)

    def on_add_wave(self, event):
        self.add_wave()
        self.triggerRedraw(1)

    def on_toggle_backend(self, event):
        world = self.scene.world
        if world.backend.name == 'glcompute':
            world.backend = NumpyBackend()
        else:
            try:
                world.backend = select_backend('gpu')
            except Exception as err:
                print('GPU backend unavailable:', err)
                return
        print('physics backend:', world.backend.name, flush=True)
        self.triggerRedraw(1)

    def build(self):
        self.scene = DemoScene(debug_flags=self.debug_flags)
        # a shallow bowl of static walls
        self.scene.add_box(size=(24, 1, 24), position=(0, -0.5, 0),
                           color=(0.5, 0.5, 0.55), dynamic=False)
        for sx, sz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if sx:
                self.scene.add_box(size=(0.5, 5, 24), position=(sx * 12, 2.5, 0),
                                   color=(0.45, 0.45, 0.5), dynamic=False)
            else:
                self.scene.add_box(size=(24, 5, 0.5), position=(0, 2.5, sz * 12),
                                   color=(0.45, 0.45, 0.5), dynamic=False)
        for _ in range(max(1, self.initial_waves)):
            self.add_wave()
        self.sg = self.scene.scene_graph()

    def add_wave(self):
        for _ in range(WAVE):
            x, z = self.rng.uniform(-9, 9, 2)
            y = self.rng.uniform(8, 18)
            if self.rng.rand() < 0.5:
                self.scene.add_box(size=(1, 1, 1), position=(x, y, z),
                                   color=(0.8, 0.7, 0.4))
            else:
                self.scene.add_sphere(radius=0.6, position=(x, y, z),
                                      color=(0.4, 0.6, 0.9))
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
    import argparse
    parser = argparse.ArgumentParser(description='Physics stress / scaling demo')
    parser.add_argument('--waves', type=int, default=1,
                        help='number of 40-body waves to drop at startup')
    parser.add_argument('--debug', action='store_true',
                        help='draw the collision-proxy wireframe overlay (slow)')
    args, _ = parser.parse_known_args()
    TestContext.initial_waves = args.waves
    TestContext.debug_flags = debugdraw.PROXIES | debugdraw.CONTACTS if args.debug else 0
    TestContext.ContextMainLoop()
