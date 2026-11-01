#! /usr/bin/env python
'''=Physics: the ball changes colour when it hits something=

[physics_stairs_colour.py-screen-0001.png Screenshot]

A body tells the script what happened to it through events. The ball of
:doc:`physics_stairs` changes colour each time it strikes anything harder than
1 m/s, stepping through red, orange, yellow, green, blue and violet and then
starting again at red.
'''
from physics_stairs import TestContext as Rolling
from physics_stairs import material_of

'''The colours the ball takes in turn, as the red, green and blue of
``baseColor``.'''
COLOURS = (
    (1.0, 0.0, 0.0),
    (1.0, 0.5, 0.0),
    (1.0, 0.9, 0.0),
    (0.0, 0.8, 0.1),
    (0.1, 0.3, 1.0),
    (0.6, 0.1, 0.9),
)


class TestContext(Rolling):
    def OnInit(self):
        '''The stairs, the ball and the push are the first tutorial's.'''
        super().OnInit()
        self.skin = material_of(self.ball)
        self.impacts = 0
        '''``addEventHandler`` is the call a context, a ``Timer`` and a
        ``TimeSensor`` already have. ``'hit'`` is a body striking something;
        ``above`` is the closing speed in metres a second that a hit must
        exceed, so the ball resting on the landing is not a hit. The handler
        is held by weak reference, which is why it is a method of the context
        and not a lambda nobody else keeps alive.'''
        self.body.addEventHandler('hit', function=self.OnBallHit, above=1.0)

    def OnBallHit(self, hit):
        '''The handler runs on the render thread, between frames, so it may
        change the scene as any other handler does. ``hit`` is a
        ``Collision``: the two bodies, the contact ``point`` and ``normal``,
        the closing ``speed`` and the ``impulse``. Each call moves the ball to
        the next of ``COLOURS``.'''
        self.skin.baseColor = COLOURS[self.impacts % len(COLOURS)]
        self.impacts += 1


if __name__ == '__main__':
    TestContext.ContextMainLoop()
