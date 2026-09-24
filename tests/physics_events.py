#! /usr/bin/env python
'''=Physics: responding to collisions=

[physics_events.py-screen-0001.png Screenshot]

The yard of ``oglc-physics-events``: crates that thud when they land, two panes
of glass, a gun and a pressure plate that opens a door.  Nothing here asks the
physics world what happened; each object subscribes a callback to its own
collisions and the physics manager calls it once per collision.

The script opens on a scene that has already been played for a moment: the
crates have been dropped, a ball has been thrown at each pane, a shot has
been fired into the brick crate and the weight is on the plate.  The left
pane broke after the solve, so its ball bounced back; the right pane broke
before it, so its ball carried on through.  The keys the demo prints play it
again.
'''
import os

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.audio import scene as audioscene
from OpenGLContext.events import systemtime
from OpenGLContext.bin.physics_events_demo import CollisionYard
from OpenGLContext.physics.demo import disable_vsync

#: How much of the scene is played before the first frame, in seconds, and in
#: steps of what length.  Fixed steps make the opening the same on every run.
OPENING = 2.0
OPENING_STEP = 1.0 / 60.0
#: When the crates are down and the shooting starts.
LANDED = 1.2


class TestContext(BaseContext):
    initialPosition = (2.5, 3.2, 12)

    def OnInit(self):
        disable_vsync()
        '''The yard builds the scene and makes every subscription.  Its
        ``__init__`` is where to read them: ``subscribe(self._thud,
        body=crates + balls, phases=('begin', 'persist'), above=IMPACT_FLOOR)``
        for the landings, ``kinds=('hit',)`` for the gun, ``kinds=('trigger',)``
        for the plate, and a subscription per pane.'''
        self.yard = CollisionYard()
        self.sg = self.yard.scene()
        for key, handler in (('d', self.yard.drop), ('l', self.yard.launch),
                             ('m', self.yard.mend), ('w', self.yard.toggle_weight),
                             (' ', self.fire)):
            self.addEventHandler('keypress', name=key,
                                 function=lambda event, handler=handler: handler())
        self.opening()
        print(__doc__)
        self._last = systemtime.systemTime()

    def opening(self):
        '''Drop the crates and the weight, then once they have landed fire at
        the brick crate and throw a ball at each pane, playing it all in fixed
        steps.  The shot is a raycast reported with ``report_hit``, which
        pushes the crate and reaches its ``'hit'`` subscribers with the next
        frame's collisions.'''
        yard = self.yard
        yard.drop()
        yard.toggle_weight()
        self.play(LANDED)
        yard.fire((1.5, 0.4, 6.0), (0.0, 0.0, -1.0))
        yard.launch()
        self.play(OPENING - LANDED)

    def play(self, seconds):
        for _ in range(round(seconds / OPENING_STEP)):
            self.yard.step(OPENING_STEP, None)

    def fire(self):
        '''The gun fires along the camera's view.'''
        platform = self.getViewPlatform()
        forward = platform.quaternion * [0.0, 0.0, -1.0, 0.0]
        self.yard.fire(platform.position[:3], forward[:3])

    def OnIdle(self, *args):
        '''The engine's clock rather than the wall's, so a capture advances
        by whole frames and lands on the same picture every time.'''
        now = systemtime.systemTime()
        dt, self._last = min(now - self._last, 0.05), now
        self.yard.step(dt, audioscene.existing_engine(self))
        self.triggerRedraw(1)
        return 1


if __name__ == '__main__':
    TestContext.ContextMainLoop()
