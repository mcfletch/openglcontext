#! /usr/bin/env python
'''=Reacting to a collision=

[using_collisions.py-screen-0001.png Screenshot]

Balls drop onto a floor and flash when they land, as hard as they landed.  The
solver has already answered the collision by the time a game hears about it;
what is left is the response on top of it -- a sound, a mark, damage, a
controller jolt -- and that is what a ``'hit'`` handler is for.

:doc:`Physics: a ball rolls down the stairs <physics_stairs>` covers making a
body and hearing of its hits, and :doc:`Physics: trigger sensors
<physics_triggers>` covers volumes that report an overlap without stopping
anything.

Keys:
    space   drop the balls again
'''
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
)
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

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
COLOUR = (0.85, 0.55, 0.3)


class Glow:
    '''One ball's flash: white-hot at the blow and back to its own colour over
    ``FADE`` seconds.

    The fade is a ``Timer``, the engine's own clock for a thing that takes a
    while: it sends a ``fraction`` event for each frame it runs, from 0 to 1,
    to the handler, so nothing here counts frames or reads a clock.'''

    def __init__(self, context, material):
        self.material = material
        self.strength = 0.0
        self.timer = Timer(duration=FADE, repeating=0)
        self.timer.addEventHandler('fraction', function=self.fade)
        self.timer.register(context)

    def flash(self, speed):
        '''The response itself.  Here it is a colour: an emissive white over
        the ball, as bright as the blow was hard.  A game puts a sound, a
        decal, a hit number or a shake of the camera in the same place, and
        scales them by the same speed.'''
        self.strength = min(speed / LOUDEST, 1.0)
        self.show(1.0)
        self.timer.start()

    def fade(self, event):
        self.show(1.0 - event.fraction())

    def show(self, left):
        glow = self.strength * left
        self.material.baseColor = tuple(
            own + (1.0 - own) * glow for own in COLOUR)
        self.material.emissiveColor = (glow, glow * 0.8, glow * 0.4)


class TestContext(BaseContext):
    initialPosition = (0, 2.6, 11)
    initialOrientation = (-1, 0, 0, 0.08)

    def OnInit(self):
        self.glows = {}
        self.build()
        self.addEventHandler('keypress', name=' ', function=self.OnDrop)
        print(__doc__)

    def build(self):
        '''A floor and some balls to drop on it.  A shape of the scene is
        static, and ``add_dynamic`` makes each ball a body that falls.'''
        stone = surfaces.pbr_material(surfaces.sandstone(256))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.55, 0.62, 0.72)]),
            DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=2.0),
            surfaces.shape(surfaces.block((14, 1, 6), repeat=3.0), stone,
                           translation=(0, -1, 0)),
        ])
        '''Each ball has a material of its own, so that it can flash alone, and
        a ``Glow`` that keeps its flash.  The handler is registered on the ball
        with ``above=BLOW``: it hears hits faster than that.'''
        for body, glow in self.glows.items():
            glow.timer.deregister(self)
            body.remove()
        self.glows = {}
        for x, height in DROPS:
            skin = PhysicalMaterial(baseColor=COLOUR, metallic=0.2, roughness=0.4)
            node = surfaces.shape(surfaces.sphere(0.5), skin)
            self.sg.children.append(node)
            body = self.physics.add_dynamic(node, translation=(x, height, 0))
            self.glows[body] = Glow(self, skin)
            body.addEventHandler('hit', function=self.OnLand, above=BLOW)
        self.physics.show_proxies(True)

    def OnDrop(self, event=None):
        self.build()

    def OnLand(self, hit):
        '''``hit.body`` is the ball that landed and ``hit.speed`` how fast it
        was closing on what it met, in metres a second, measured before the
        solver cancelled it.  Every hit of every step reaches the handler, so a
        game that must not miss a blow -- a scoring hit, a breakable -- does not
        have to step the world itself to hear it.'''
        self.glows[hit.body].flash(hit.speed)
        print('body %d landed at %.1f m/s' % (hit.body.uid, hit.speed))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
