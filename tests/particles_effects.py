#! /usr/bin/env python
'''=Particle Effects (instanced quads)=

[particles_effects.py-screen-0001.png Screenshot]

Five particle systems side by side, each one preset from
`OpenGLContext.scenegraph.particles`, so what each effect is made of can
be read off against what it looks like:

 * *fire* -- a continuous emitter with upward gravity and a hot-to-dark
   colour ramp.
 * *smoke* -- alpha-blended rather than additive, growing as it rises and
   fading out.
 * *sparks* -- a burst, heavy gravity, tiny and short-lived.
 * *explosion* -- a big burst into a full sphere, with drag to make it
   bloom and stop.
 * *trail* -- a slow, wide, drifting puff of the sort a rocket leaves.

Every system is one `ParticleEmitter` node under a `Transform`, drawn in
a single instanced call, and none of them loads a texture: without one a
particle is a soft round dot computed in the fragment shader.

Press the space bar to set the two burst effects off again, `p` to pause
and resume emission, and the usual keys to walk around.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph import particles
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, Material, Shape, Transform,
)

#: Which preset goes where along the X axis, left to right.
LAYOUT = [
    ('fire', -6.0),
    ('smoke', -3.0),
    ('sparks', 0.0),
    ('explosion', 3.0),
    ('trail', 6.0),
]

#: Seconds between automatic re-firings of the burst effects, so the demo
#: keeps showing them without anyone holding the space bar down.
BURST_INTERVAL = 1.2


class TestContext(BaseContext):
    """One transform per preset, one emitter under each."""

    initialPosition = (0, 3, 13)

    def OnInit(self):
        BaseContext.OnInit(self)
        self.emitters = []
        children = []
        for name, x in LAYOUT:
            # A fixed seed makes the reference image reproducible; a game
            # would leave it alone and let each emitter differ.
            emitter = particles.preset(name, seed=17)
            self.emitters.append(emitter)
            children.append(Transform(translation=(x, 0.0, 0.0),
                                      children=[emitter]))
        # A dull floor, so the effects are seen against something and the
        # depth test can be seen doing its job: particles are depth-*tested*
        # against the world even though they never write depth themselves.
        children.append(Transform(translation=(0.0, -1.2, 0.0), children=[
            Shape(appearance=Appearance(
                      material=Material(diffuseColor=(0.16, 0.17, 0.2))),
                  geometry=Box(size=(24.0, 0.4, 10.0)))]))
        self.sg = Transform(children=children)
        self.addEventHandler('keypress', name=' ', function=self.OnFire)
        self.addEventHandler('keypress', name='p', function=self.OnPause)
        self.timer = Timer(duration=BURST_INTERVAL, repeating=1)
        self.timer.addEventHandler('cycle', self.OnCycle)
        self.timer.register(self)
        self.timer.start()
        print(__doc__)

    def bursts(self):
        """The emitters that fire rather than run continuously."""
        return [e for e in self.emitters if e.burst > 0]

    def OnFire(self, event):
        for emitter in self.bursts():
            emitter.fire()
        self.triggerRedraw(1)

    def OnCycle(self, event):
        self.OnFire(event)

    def OnPause(self, event):
        """Stop emitting without freezing what is already in the air."""
        for emitter in self.emitters:
            emitter.enabled = not emitter.enabled
        self.triggerRedraw(1)

    def OnIdle(self, event=None):
        # Particles are stepped from the draw, so a still frame is a stopped
        # simulation: an effects demo has to keep asking for frames.
        self.triggerRedraw(1)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
