#! /usr/bin/env python
'''=Physics: a new material=

[physics_stairs_material.py-screen-0001.png Screenshot]

A material says how a surface grips and bounces. Four are defined from the
start: ``wood``, ``metal``, ``rubber`` and ``ice``. ``physics.materials.define``
adds others, and a body takes one by name. The stairs of
:doc:`physics_stairs` become wet stone: slippery, and dead to a bounce.
'''
from physics_stairs import START, StairsContext


class TestContext(StairsContext):
    def OnInit(self):
        super().OnInit()
        '''``friction`` is the coefficient of friction, as a pair of surfaces
        slides and as they hold; 0.1 is nearly ice and 1.0 is rubber on
        concrete. ``restitution`` is the fraction of the closing speed a bounce
        returns, from 0 for clay to 1 for a bounce that loses nothing. Where two
        bodies meet, each coefficient is the average of the two materials'.'''
        self.physics.materials.define('wet-stone', friction=0.1, restitution=0.05)
        '''The stairs are in the scene, so they are already static. Adding them
        again with a material replaces the body the scene made for them. Doing it
        before the first frame, as here, means the scene's body is never made.'''
        self.stairs_body = self.physics.add_static(self.stairs, material='wet-stone')
        self.body = self.physics.add_dynamic(
            self.ball, translation=START, mass=2.0, restitution=0.4)
        self.body.apply_impulse((0, 0, 8))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
