#! /usr/bin/env python
'''=Physics: reacting on the physics thread=

[physics_stairs_thread.py-screen-0001.png Screenshot]

A handler normally runs on the render thread, after the frame's physics is
done. A handler marked ``@Context.physics_callback`` runs on the thread that
steps the world, right after the step that caused the event, with the world as
that step left it. The ball turns red as before; the difference is the thread
the handler runs on and how it reaches the scene.
'''
from physics_stairs import TestContext as Rolling
from physics_stairs import material_of


class TestContext(Rolling):
    def OnInit(self):
        super().OnInit()
        self.skin = material_of(self.ball)
        self.body.addEventHandler('hit', function=self.OnBallHit, above=1.0)

    '''The marker is the only change to the registration. ``physics_callback``
    sets an attribute on the function and nothing else; a direct call still
    runs the function on the calling thread. The class body of a context
    already has ``Context`` in scope, so there is no import.'''
    @Rolling.physics_callback
    def OnBallHit(self, hit):
        '''Scene fields belong to the render thread, which may be drawing
        right now, so this handler does not assign ``self.skin.baseColor``.
        ``physics.render.set`` queues the assignment and the engine applies it
        before the next frame is drawn. A field set twice for one node in one
        tick is applied once, with the last value. A handler of this kind may
        call any ``Body`` method directly; the call takes effect in the step
        that follows.'''
        self.physics.render.set(self.skin, baseColor=(1, 0, 0))


if __name__ == '__main__':
    TestContext.ContextMainLoop()
