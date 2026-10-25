#! /usr/bin/env python
'''=Physics: turning it off and tuning it=

[physics_stairs_tuning.py-screen-0001.png Screenshot]

The world runs from the first body to the last, and a script has three ways to
change that. It can pause the world and start it again, change the length of
its step, and make the ball start over. A game that wants no physics at all
declares it.

Keys:
    p   pause and resume
    f   a finer step, 240 steps a second
    r   put the ball back on the landing and roll it again
'''
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.physics.settings import PhysicsDefinition

from physics_stairs import START
from physics_stairs import TestContext as Rolling


class TestContext(Rolling):
    '''A definition declares what a program wants before the window opens.
    ``tickHz`` is the length of the fixed step in steps a second, and it is
    the same in every mode: a frame runs as many whole steps as its time
    holds, up to ``maxCatchUp`` seconds, and drops the rest. ``enabled=False``
    starts no world, makes no colliders and leaves every body where it is
    put; ``OPENGLCONTEXT_PHYSICS=0`` says the same from the environment.'''
    contextDefinition = ContextDefinition(
        physics=PhysicsDefinition(tickHz=120.0, maxCatchUp=0.1))

    def OnInit(self):
        super().OnInit()
        self.paused = False
        for key, handler in (('p', self.OnPause), ('f', self.OnFine), ('r', self.OnReset)):
            self.addEventHandler('keypress', name=key, function=handler)

    def OnPause(self, event):
        '''``enable(False)`` stops stepping; every body stays where it is and
        the window asks for no more frames. ``enable(True)`` carries on.'''
        self.paused = not self.paused
        self.physics.enable(not self.paused)

    def OnFine(self, event):
        '''``tick_frequency`` sets the step from now on. A finer step costs
        more time a frame and keeps a fast, small body from passing through a
        thin one.'''
        self.physics.enable(True, tick_frequency=240)

    def OnReset(self, event):
        '''Assigning to ``ball.translation`` does not move a body, because the
        world owns the pose and the next step would write its own over it.
        ``set_transform`` and ``set_velocity`` are how a body is moved.'''
        self.body.set_transform(translation=START)
        self.body.set_velocity((0, 0, 0))
        self.body.apply_impulse((0, 0, 8))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
