#! /usr/bin/env python
'''=Physics: first-person navigation=

[physics_navigate.py-screen-0001.png Screenshot]

Walk through a level with walls, a doorway, a staircase, and a ramp using the
:class:`PhysicsViewPlatform` character controller.  The capsule can't clip walls,
climbs steps up to ``stepHeight``, and slides on steep slopes.  On bind it runs
**safe viewpoint binding** so the camera never starts stuck in the floor.

The demo starts by auto-walking so it explores on its own; press **t** to take
over and drive it yourself.

Keys:
    t               toggle auto-walk on/off
    w / s           walk forward / back      a / d   strafe left / right
    q / e           turn left / right        shift-w run (hold w, then r)
    space           jump                     f       toggle fly
'''
import time
import numpy as np

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.physics.demo import DemoScene, disable_vsync
from omi_physics.character import CharacterCapabilities
from OpenGLContext.move.physicsplatform import PhysicsViewPlatform

HOLD = 0.25            # seconds a key press keeps driving movement (key-repeat refreshes it)


class TestContext(BaseContext):
    def OnInit(self):
        disable_vsync()
        self.scene = DemoScene(debug_flags=0, background=(0.55, 0.62, 0.72))
        build_level(self.scene)
        self.headlight = basenodes.PointLight(
            location=(0, 2, 0), color=(1, 1, 0.95), intensity=0.8, radius=40)
        sun = basenodes.DirectionalLight(direction=(-0.4, -1, -0.5),
                                         color=(1, 0.98, 0.9), intensity=0.7)
        self.sg = self.scene.scene_graph(extra=[sun, self.headlight])

        self.platform_nav = PhysicsViewPlatform(
            self.scene.world, CharacterCapabilities(walkSpeed=3.0, runSpeed=6.0,
                                                    stepHeight=0.4), yaw=0.0)
        self.platform_nav.bind((-8.0, 2.0, 6.0))
        # ViewPlatformMixin binds a default Smooth movement manager (arrow keys)
        # to context.platform. PhysicsViewPlatform now owns the camera and writes
        # it every frame via nav.apply(), so the two fight: while a built-in-nav
        # key is held its interpolator glides the camera (its timer fires from
        # DoEventCascade, after our nav.apply), then on release the timer stops
        # and nav.apply snaps the camera back to the character pose. Unbind it so
        # the character controller is the sole driver.
        if self.movementManager is not None:
            self.movementManager.unbind(self)
            self.movementManager = None
        self._auto = True
        self._stuck_frames = 0
        self._prev = self.platform_nav.character.position.copy()
        self._keys = {}
        self._run = False
        print(__doc__)
        # Handlers must be bound methods: the event system holds them weakly, so
        # a lambda with no other reference would be collected and never fire.
        #
        # Movement binds to 'keyboard' (key-down), NOT 'keypress' (a typed
        # character): only 'keyboard' events are re-emitted by key-repeat (native,
        # or the software repeat the GLFW Wayland backend needs), so *holding* w/a/
        # s/d keeps driving movement instead of firing once and stopping (which on
        # a ramp just slid you back down). The one-shot toggles below stay on
        # 'keypress' so a held key doesn't retrigger them.
        for k in 'wsadqe':
            self.addEventHandler('keyboard', name=k, state=1, function=self._on_key)
        self.addEventHandler('keypress', name='t', function=self._toggle_auto)
        self.addEventHandler('keypress', name='r', function=self._toggle_run)
        self.addEventHandler('keypress', name=' ', function=self._on_jump)
        self.addEventHandler('keypress', name='f', function=self._toggle_fly)
        # Fire the software key-repeat quickly so a held key doesn't stutter in the
        # gap between the initial press and the first repeat (HOLD is 0.25 s).
        self.keyRepeatDelay = 0.1
        self._last = time.time()

    def _on_key(self, event):
        self._auto = False
        self._keys[event.name] = time.time()

    def _toggle_auto(self, event):
        self._auto = not self._auto
        print('auto-walk', 'on' if self._auto else 'off')

    def _toggle_run(self, event):
        self._run = not self._run

    def _on_jump(self, event):
        self.platform_nav.jump()

    def _toggle_fly(self, event):
        self.platform_nav.set_fly(not self.platform_nav.character.flying)

    def OnIdle(self, *args):
        now = time.time()
        dt = min(now - self._last, 0.05)
        self._last = now
        nav = self.platform_nav
        if self._auto:
            self._auto_walk()
        else:
            self._manual(now, nav, dt)
        nav.update(dt)
        self.headlight.location = nav.camera_position()
        nav.apply(self)
        self.triggerRedraw(1)
        return 1

    def _manual(self, now, nav, dt):
        def held(k):
            return now - self._keys.get(k, 0) < HOLD
        forward = (1.0 if held('w') else 0.0) - (1.0 if held('s') else 0.0)
        strafe = (1.0 if held('d') else 0.0) - (1.0 if held('a') else 0.0)
        if held('q'):
            nav.turn(-2.0 * dt)         # q: turn left
        if held('e'):
            nav.turn(2.0 * dt)          # e: turn right
        mode = 'run' if self._run else 'walk'
        if nav.character.flying:
            nav.set_fly_move(forward=forward, strafe=strafe)
        else:
            nav.set_move(forward=forward, strafe=strafe, mode=mode)

    def _auto_walk(self):
        nav = self.platform_nav
        moved = np.linalg.norm((nav.character.position - self._prev)[[0, 2]])
        if moved < 0.005:
            self._stuck_frames += 1
            if self._stuck_frames > 5:
                nav.turn(0.6)
                self._stuck_frames = 0
        else:
            self._stuck_frames = 0
        self._prev = nav.character.position.copy()
        nav.set_move(forward=1.0, mode='walk')


def build_level(scene):
    scene.add_box(size=(24, 1, 24), position=(0, -0.5, 0),
                  color=(0.62, 0.60, 0.55), dynamic=False)
    for sx in (1, -1):
        scene.add_box(size=(0.4, 4, 24), position=(sx * 12, 2, 0),
                      color=(0.78, 0.72, 0.62), dynamic=False)
    for sz in (1, -1):
        scene.add_box(size=(24, 4, 0.4), position=(0, 2, sz * 12),
                      color=(0.78, 0.72, 0.62), dynamic=False)
    # interior wall with a doorway (two segments, a gap between)
    scene.add_box(size=(0.4, 4, 8), position=(0, 2, -8),
                  color=(0.82, 0.68, 0.55), dynamic=False)
    scene.add_box(size=(0.4, 4, 8), position=(0, 2, 8),
                  color=(0.82, 0.68, 0.55), dynamic=False)
    # a staircase
    for k in range(5):
        scene.add_box(size=(3, 0.3, 2), position=(6, 0.15 + k * 0.3, -6 + k * 0.9),
                      color=(0.85, 0.78, 0.55), dynamic=False)
    # a ramp
    angle = np.radians(20)
    scene.add_box(size=(6, 0.4, 4), position=(-7, 1.0, -6),
                  color=(0.6, 0.72, 0.85), dynamic=False, rotation=(0, 0, 1, angle))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
