#! /usr/bin/env python
'''=Physics: responding to collisions=

[physics_events.py-screen-0001.png Screenshot]

The yard of ``oglc-physics-events``: crates that thud when they land, two panes
of glass, a gun and a pressure plate that opens a door.  Nothing here asks the
physics world what happened; each body registers a handler for its own
collisions and the physics service calls it once per collision.

The script opens on a scene that has already been played for a moment: the
crates have been dropped, a ball has been thrown at each pane, a shot has
been fired into the brick crate and the weight is on the plate.  The left
pane broke after the solve, so its ball bounced back; the right pane broke
before it, so its ball carried on through.  The keys the demo prints play it
again.
'''
from OpenGLContext.bin.physics_events_demo import (
    CollisionYard, MASTER_GAIN, definition,
)
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.contextdefinition import ContextDefinition

#: How much of the scene is played before the first frame, in seconds, and in
#: steps of what length.  Fixed steps make the opening the same on every run.
OPENING = 2.0
OPENING_STEP = 1.0 / 60.0
#: When the crates are down and the shooting starts.
LANDED = 1.2


class TestContext(BaseContext):
    '''The physics world is declared by the yard: ``definition()`` steps it in
    the frame, so the opening below plays the same on every run.'''
    renderer = 'pbr'
    initialPosition = (2.5, 3.2, 12)
    contextDefinition = ContextDefinition(physics=definition())

    def OnInit(self):
        '''The yard builds the scene and makes every handler.  Its
        ``__init__`` is where to read them: ``body.addEventHandler('hit',
        function=self._thud, above=IMPACT_FLOOR)`` for each crate and ball,
        a ``hit`` handler on each pane, ``enter`` and ``exit`` on the plate,
        ``collision_filter=`` so a pane's shards let its ball through, and
        ``physics.set_contact_filter`` to let a ball through a pane that the
        blow breaks.
        It is given the context's ``physics`` and ``audio``; nothing in the
        script steps the world.'''
        self.yard = CollisionYard(self.physics, self.audio)
        self.sg = self.yard.scene()
        '''``audio.mix`` sets the level of the whole mix, and the player's
        volume is applied over it.'''
        self.audio.mix = MASTER_GAIN
        for key, handler in (('d', self.yard.drop), ('l', self.yard.launch),
                             ('m', self.yard.mend), ('w', self.yard.toggle_weight),
                             (' ', self.fire)):
            self.addEventHandler('keypress', name=key,
                                 function=lambda event, handler=handler: handler())
        self.opening()
        print(__doc__)

    def opening(self):
        '''Drop the crates and the weight, then once they have landed fire at
        the brick crate and throw a ball at each pane.  ``physics.frame(dt)``
        steps the world by ``dt`` seconds and delivers what happened, which is
        what the frame hook does with each frame's time; calling it by hand
        gives a scene already in progress before the first frame is drawn.
        The shot is a ``raycast`` and an impulse where the round struck.'''
        yard = self.yard
        yard.drop()
        yard.toggle_weight()
        self.play(LANDED)
        yard.fire((1.5, 0.4, 6.0), (0.0, 0.0, -1.0))
        yard.launch()
        self.play(OPENING - LANDED)

    def play(self, seconds):
        for _ in range(round(seconds / OPENING_STEP)):
            self.physics.frame(OPENING_STEP)

    def fire(self):
        '''The gun fires along the camera's view.'''
        platform = self.getViewPlatform()
        self.yard.fire(platform.position[:3], platform.forward())


if __name__ == '__main__':
    TestContext.ContextMainLoop()
