#! /usr/bin/env python
'''=Physics: first-person navigation=

[physics_navigate.py-screen-0001.png Screenshot]

Walk through a level with walls, a doorway, a staircase, and a ramp as a
physics *character*: a capsule the service steps each frame.  The capsule can't
clip walls, climbs steps up to ``stepHeight``, and slides on steep slopes.
``PhysicsViewPlatform.over`` puts the camera at its eyes, and on bind it runs
**safe viewpoint binding** so the camera never starts stuck in the floor.

The demo starts by auto-walking so it explores on its own; press **t** to take
over and drive it yourself.

Keys:
    t               toggle auto-walk on/off
    w / s           walk forward / back      a / d   strafe left / right
    q / e           turn left / right        shift-w run (hold w, then r)
    space           jump                     f       toggle fly
'''
import numpy as np
from omi_physics.character import CharacterCapabilities

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.events import systemtime
from OpenGLContext.events.framestep import FrameStep
from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
from OpenGLContext.scenegraph import basenodes, surfaces

HOLD = 0.25            # seconds a key press keeps driving movement (key-repeat refreshes it)


class TestContext(BaseContext):
    def OnInit(self):
        level = build_level()
        self.floor = level[0]
        self.sg = basenodes.sceneGraph(children=[
            basenodes.SimpleBackground(color=(0.55, 0.62, 0.72)),
            *level,
        ])
        self.headlight = basenodes.PointLight(
            location=(0, 2, 0), color=(1, 1, 0.95), intensity=0.8, radius=40)
        self.sg.children.append(self.headlight)
        self.sg.children.append(basenodes.DirectionalLight(
            direction=(-0.4, -1, -0.5), color=(1, 0.98, 0.9), intensity=0.7))
        '''The shapes of the scene are static bodies, made as the scene is first
        drawn.  The floor is made at once, so the walker has ground in the
        first frame.'''
        self.physics.add_static(self.floor, proxy='box')
        '''``add_character`` makes a walker.  Its ``CharacterCapabilities`` are its
        speeds in metres a second, the height of the step it climbs and its
        capsule; ``PhysicsViewPlatform.over`` is the camera at its eyes.'''
        self.hero = self.physics.add_character(
            capabilities=CharacterCapabilities(walkSpeed=3.0, runSpeed=6.0, stepHeight=0.4),
            position=(-8.0, 0.3, 6.0))
        self.platform_nav = PhysicsViewPlatform.over(self.hero, yaw=0.0)
        # ViewPlatformMixin binds a default Smooth movement manager (arrow keys)
        # to context.platform. The platform owns the camera and writes it every
        # frame via nav.apply(), so the two fight: unbind it so the character
        # is the sole driver.
        if self.movementManager is not None:
            self.movementManager.unbind(self)
            self.movementManager = None
        self._auto = True
        self._stuck_frames = 0
        self._prev = self.hero.position.copy()
        self._keys = {}
        self._run = False
        self._steps = FrameStep(longest=0.05)
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

    def _on_key(self, event):
        self._auto = False
        self._keys[event.name] = systemtime.systemTime()

    def _toggle_auto(self, event):
        self._auto = not self._auto
        print('auto-walk', 'on' if self._auto else 'off')

    def _toggle_run(self, event):
        self._run = not self._run

    def _on_jump(self, event):
        self.hero.jump()

    def _toggle_fly(self, event):
        self.hero.set_fly(not self.hero.controller.flying)

    def OnIdle(self, *arguments):
        '''The service steps the walker before every frame.  What is left to
        the script is the input: what the keys ask for, and the camera where
        the walker has got to.'''
        now = systemtime.systemTime()
        dt = self._steps.step(now)
        nav = self.platform_nav
        if self._auto:
            self._auto_walk()
        else:
            self._manual(now, nav, dt)
        self.headlight.location = tuple(self.hero.eye)
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
        if self.hero.controller.flying:
            nav.set_fly_move(forward=forward, strafe=strafe)
        else:
            nav.set_move(forward=forward, strafe=strafe, mode=mode)

    def _auto_walk(self):
        nav = self.platform_nav
        moved = np.linalg.norm((self.hero.position - self._prev)[[0, 2]])
        if moved < 0.005:
            self._stuck_frames += 1
            if self._stuck_frames > 5:
                nav.turn(0.6)
                self._stuck_frames = 0
        else:
            self._stuck_frames = 0
        self._prev = self.hero.position.copy()
        nav.set_move(forward=1.0, mode='walk')


def build_level():
    '''A walled room with a doorway, a staircase and a ramp, as shapes.'''
    floor = surfaces.pbr_material(surfaces.checkered_marble(512, tiles=6))
    outer = surfaces.pbr_material(surfaces.sandstone(256))
    inner = surfaces.pbr_material(surfaces.plaster(256))
    step = surfaces.pbr_material(surfaces.brick(256))
    slab = surfaces.pbr_material(surfaces.tiles(256, count=6))
    parts = []
    for sx in (1, -1):
        parts.append(surfaces.shape(surfaces.block((0.4, 4, 24)), outer, translation=(sx * 12, 2, 0)))
    for sz in (1, -1):
        parts.append(surfaces.shape(surfaces.block((24, 4, 0.4)), outer, translation=(0, 2, sz * 12)))
    # interior wall with a doorway (two segments, a gap between)
    parts.append(surfaces.shape(surfaces.block((0.4, 4, 8)), inner, translation=(0, 2, -8)))
    parts.append(surfaces.shape(surfaces.block((0.4, 4, 8)), inner, translation=(0, 2, 8)))
    # a staircase
    for k in range(5):
        parts.append(surfaces.shape(surfaces.block((3, 0.3, 2)), step,
                                    translation=(6, 0.15 + k * 0.3, -6 + k * 0.9)))
    # a ramp
    parts.append(surfaces.shape(surfaces.block((6, 0.4, 4)), slab, translation=(-7, 1.0, -6),
                                rotation=(0, 0, 1, np.radians(20))))
    return [surfaces.shape(surfaces.block((24, 1, 24), repeat=4.0), floor,
                           translation=(0, -0.5, 0)), *parts]


if __name__ == '__main__':
    TestContext.ContextMainLoop()
