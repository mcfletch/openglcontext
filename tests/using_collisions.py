#! /usr/bin/env python
'''=Reacting to a collision=

[using_collisions.py-screen-0001.png Screenshot]

Balls drop onto a floor and flash when they land, as hard as they landed.  The
solver has already answered the collision by the time a game hears about it;
what is left is the response on top of it -- a sound, a mark, damage, a
controller jolt -- and that is what ``PhysicsWorld.impact_on`` is for.

:doc:`Physics: objects falling into a room <physics_room_drop>` covers building
a world, and :doc:`Physics: trigger sensors <physics_triggers>` covers volumes
that report an overlap without stopping anything.

Keys:
    space   drop the balls again
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

'''``systemTime`` is the engine's own clock rather than the wall clock.  A
recording or a capture replaces it with one that advances a frame's worth per
frame drawn, so a scene stepped from it runs at the same rate however long the
frames took.'''
from OpenGLContext.events.systemtime import systemTime
from OpenGLContext.physics.demo import DemoScene, disable_vsync
from OpenGLContext.physics import debugdraw

#: How fast two bodies must be closing for the landing to count, in metres a
#: second.  Not zero: a body resting on the floor is still being pressed into
#: it by gravity, so it reads a small closing speed on every step for as long
#: as it sits there.
BLOW = 1.0
#: The speed a flash is at its brightest, in metres a second.
LOUDEST = 8.0
#: Seconds a flash takes to fade.
FADE = 0.5
#: Where the balls start, as ``(x, height)``.
DROPS = [(-3.0, 4.0), (-1.5, 6.0), (0.0, 8.0), (1.5, 6.5), (3.0, 5.0)]


class TestContext(BaseContext):
    initialPosition = (0, 2.6, 11)
    initialOrientation = (-1, 0, 0, 0.08)

    def OnInit(self):
        disable_vsync()
        self.build()
        self.addEventHandler('keypress', name=' ', function=self.OnDrop)
        self.last = systemTime()
        print(__doc__)

    def build(self):
        '''A floor and some balls to drop on it.  ``DemoScene`` keeps the
        scenegraph and the physics world in step: each ``add_*`` call makes
        both the node that is drawn and the body that is simulated.'''
        self.scene = DemoScene(debug_flags=debugdraw.PROXIES)
        self.scene.add_box(size=(14, 1, 6), position=(0, -1, 0),
                           color=(0.4, 0.42, 0.45), dynamic=False)
        '''Each ball is kept by its body index, which is how the world names a
        body, together with the material to flash and the colour to fade back
        to.'''
        self.balls = {}
        for x, height in DROPS:
            body = self.scene.add_sphere(radius=0.5, position=(x, height, 0),
                                         color=(0.85, 0.55, 0.3))
            material = body.transform.children[0].appearance.material
            self.balls[body.index] = (material, tuple(material.diffuseColor))
        self.scene.advance(0.0)
        self.sg = self.scene.scene_graph()

    def OnDrop(self, event=None):
        self.build()
        self.triggerRedraw(1)

    def OnIdle(self, event=None):
        now = systemTime()
        step = min(now - self.last, 0.05)
        self.last = now
        '''``advance`` runs the world forward and writes the new poses onto the
        scene nodes.'''
        active = self.scene.advance(step)
        self.respond(step)
        if active:
            self.triggerRedraw(1)

    def respond(self, step):
        '''``impact_on`` answers the heaviest blow a body took in the step just
        run, as ``(other body, closing speed)``, or ``None``.  Read it after
        ``advance`` and before the next one: contacts are rebuilt every step,
        and the speed recorded is the one from before the solve cancelled it.

        A frame is usually several physics steps, so a frame that reads once
        sees the last step of the frame.  For a game that must not miss a blow
        -- a scoring hit, a breakable -- step the world itself and ask after
        each step.'''
        for index, (material, colour) in self.balls.items():
            blow = self.scene.world.impact_on(index, above=BLOW)
            if blow is not None:
                other, speed = blow
                self.flash(material, speed)
                print('body %d landed at %.1f m/s' % (index, speed))
            else:
                self.cool(material, colour, step)

    def flash(self, material, speed):
        '''The response itself.  Here it is a colour: an emissive white over
        the ball, as bright as the blow was hard.  A game puts a sound, a
        decal, a hit number or a shake of the camera in the same place, and
        scales them by the same speed.'''
        strength = min(speed / LOUDEST, 1.0)
        material.diffuseColor = (1.0, 0.95, 0.8)
        material.emissiveColor = (strength, strength * 0.8, strength * 0.4)

    def cool(self, material, colour, step):
        """Fade what the last blow left, back towards the ball's own colour."""
        fade = min(step / FADE, 1.0)
        material.emissiveColor = tuple(value * (1.0 - fade)
                                       for value in material.emissiveColor)
        material.diffuseColor = tuple(
            was + (want - was) * fade
            for was, want in zip(material.diffuseColor, colour))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
