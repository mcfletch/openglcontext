#! /usr/bin/env python
'''=Physics: first-person navigation=

[physics_navigate.py-screen-0001.png Screenshot]

Walk through a level with walls, a doorway, a staircase and a ramp as a physics
character: a capsule the service steps each frame. Walls stop it, it climbs
steps up to ``stepHeight`` and it slides on slopes too steep to stand on.

``self.follow(hero, view='eyes')`` puts the camera at the character's eyes and
gives it the keys of the engine's walk and fly modes. The script has no clock,
no key table and no per-frame code.

Keys:
    w / s           walk forward / back      a / d   step left / right
    q / e           turn left / right        shift   run
    space           jump                     f       fly, and walk again
'''
import numpy as np

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.physics import CharacterCapabilities
from OpenGLContext.scenegraph import basenodes, surfaces


class TestContext(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(children=[
            basenodes.SimpleBackground(color=(0.55, 0.62, 0.72)),
            basenodes.DirectionalLight(direction=(-0.4, -1, -0.5), color=(1, 0.98, 0.9),
                                       intensity=1.6),
            basenodes.DirectionalLight(direction=(0.5, -0.6, 0.6), color=(0.8, 0.85, 1.0),
                                       intensity=0.6),
            *build_level(),
        ])
        '''``add_character`` makes a walker. Its ``CharacterCapabilities`` are
        its speeds in metres a second, the height of the step it climbs and its
        capsule. The shapes of the scene are static bodies, so the walls, the
        stairs and the ramp stop it without being mentioned.'''
        self.hero = self.physics.add_character(
            capabilities=CharacterCapabilities(walkSpeed=3.0, runSpeed=6.0, stepHeight=0.4),
            position=(-8.0, 0.3, 6.0))
        '''``follow`` with ``view='eyes'`` is the first-person view: the camera
        is at the character's eyes, the movement keys walk it, and the free-fly
        navigator that held the camera is unbound until ``unfollow``. ``yaw`` is
        the heading in radians about +Y; 0 looks along -Z.'''
        self.walker = self.follow(self.hero, view='eyes', yaw=0.0)
        print(__doc__)
        self.addEventHandler('keypress', name='f', function=self.on_fly)

    def on_fly(self, event):
        '''The walker's ``navigation`` holds its movement modes. Selecting the
        fly mode lifts the character off the ground; selecting walk drops it.'''
        flying = self.walker.navigation.current.name == 'fly'
        self.walker.navigation.select('walk' if flying else 'fly')


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
