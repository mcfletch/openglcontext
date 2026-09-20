#! /usr/bin/env python
'''=Animating a transform=

[using_animation.py-screen-0001.png Screenshot]

Moving something in the scene as time passes.  Two boxes turn on the spot and
a third slides between them, driven by a `Timer`: the engine's own clock,
rather than the wall clock, so a recorded session and a capture run at the
same rate as the frames they are drawing.
'''
import math

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
'''A ``Timer`` reports where it has got to.  ``duration`` is how long one
cycle takes in seconds and ``repeating`` starts it again at the end of each
one.'''
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Transform,
    sceneGraph,
)

#: Seconds for one full turn.
PERIOD = 6.0


class TestContext(BaseContext):
    initialPosition = (0, 0.9, 7)
    initialOrientation = (-1, 0, 0, 0.13)      # pitched a little downward

    def OnInit(self):
        '''The nodes to be animated are kept as attributes, because the
        handler below has to reach them every frame.  Nothing about them is
        special: they are ordinary ``Transform`` nodes with a ``Shape`` under
        each.'''
        self.left = Transform(translation=(-2.5, 0, 0), children=[
            box((0.85, 0.35, 0.25)),
        ])
        self.right = Transform(translation=(2.5, 0, 0), children=[
            box((0.25, 0.45, 0.85)),
        ])
        self.middle = Transform(children=[box((0.85, 0.8, 0.3))])
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.12, 0.13, 0.16)]),
            DirectionalLight(direction=(-0.3, -0.7, -0.6)),
            self.left, self.right, self.middle,
        ])
        '''The timer is registered with the context and started.  ``fraction``
        is delivered every frame with how far through the current cycle the
        timer is, from 0.0 to 1.0; ``cycle`` is delivered once at the end of
        each one.'''
        self.timer = Timer(duration=PERIOD, repeating=1)
        self.timer.addEventHandler('fraction', self.OnFraction)
        self.timer.register(self)
        self.timer.start()
        print(__doc__)

    def OnFraction(self, event):
        '''Setting a field is the whole of animating a scene.  A node's fields
        are observed, so writing one marks what has to be redrawn and asks for
        a new frame; there is no separate "update the renderer" step.

        ``rotation`` is a VRML97 ``SFRotation``: an axis and an angle in
        radians, as ``(x, y, z, radians)``.'''
        fraction = event.fraction()
        turn = 2.0 * math.pi * fraction
        self.left.rotation = (0, 1, 0, turn)
        self.right.rotation = (0, 1, 0, -turn)
        '''``translation`` is three numbers.  A sine of the same fraction
        carries the middle box from one side to the other and back within the
        cycle, rather than jumping back at the end of it.'''
        self.middle.translation = (2.5 * math.sin(turn), 0, 0)


def box(colour):
    """A unit box of one colour, as a `Shape`."""
    return Shape(
        geometry=Box(size=(1, 1, 1)),
        appearance=Appearance(material=Material(diffuseColor=colour)),
    )


'''A ``TimeSensor`` and an interpolator node do the same thing declaratively,
written into the scene rather than into a handler, which is what a ``.wrl``
file or an authored glTF animation uses -- see :doc:`Light Nodes, ROUTEs
<lightobject>` for that form, and :doc:`Playing a canned animation
<using_clips>` for the clips a model brings with it.'''

if __name__ == "__main__":
    TestContext.ContextMainLoop()
