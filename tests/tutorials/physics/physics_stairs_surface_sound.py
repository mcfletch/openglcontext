#! /usr/bin/env python
'''=Physics: a sound on the material=

[physics_stairs_surface_sound.py-screen-0001.png Screenshot]

A sound on a material plays wherever a body of that material is struck harder
than 1 m/s, at the contact point, with a gain that reaches 1.0 at 6 m/s. The
script has no handler. Every body that is made of the material sounds alike,
which is what a surface does.
'''
from OpenGLContext.audio import sounds

from physics_stairs import START, StairsContext

THUD = sounds.impact(0.25, decay=18.0, seed=7)


class TestContext(StairsContext):
    def OnInit(self):
        super().OnInit()
        '''``sound=`` takes what ``audio.play`` takes. The material is defined
        before a body takes it, because a body is told whether to report its
        strikes when it is made.'''
        self.physics.materials.define(
            'wet-stone', friction=0.1, restitution=0.05, sound=THUD)
        self.physics.add_static(self.stairs, material='wet-stone')
        self.body = self.physics.add_dynamic(
            self.ball, translation=START, mass=2.0, restitution=0.4)
        self.body.apply_impulse((0, 0, 8))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
