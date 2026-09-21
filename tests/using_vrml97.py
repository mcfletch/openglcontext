#! /usr/bin/env python
'''=Loading a VRML97 model=

[using_vrml97.py-screen-0001.png Screenshot]

A ``.wrl`` file is a scenegraph written down, and this engine's scenegraph
is VRML97's, so loading one is reading the nodes it names.  The file used
here animates itself: it carries a ``TimeSensor``, two interpolators and
the ``ROUTE``\\ s that wire them to a ``Transform``, so it moves with no
code at all.

:doc:`The VRML97 page </vrml97>` is what the format holds and what this
engine does with it; this is how to put one on screen.

Keys:

    space   turn the file's own animation on and off
'''
import os

from OpenGLContext import testingcontext
'''``Loader`` is the one entry point for every format the engine reads: it
looks at the name, picks the handler for it, and answers a scenegraph.'''
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, Transform, sceneGraph,
)

BaseContext = testingcontext.getInteractive()

#: The file, beside this script.  It is a pyramid on a looping path -- the
#: animation is in the file rather than in this program.
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, 'wrls', 'positioninterpolator.wrl')

#: Seconds for one turn of the whole model, driven from Python below.
PERIOD = 12.0


class TestContext(BaseContext):
    initialPosition = (0, 1.1, 4.2)
    initialOrientation = (-1, 0, 0, 0.12)

    def OnInit(self):
        '''``Loader.load`` takes a path or a URL and answers the scene the
        file describes -- nodes, materials, lights, sensors and routes.  The
        result is a scenegraph like any other, so it can be mounted under a
        ``Transform`` and put in a scene of your own.'''
        loaded = Loader.load(MODEL)
        print('%s: %d root nodes' % (os.path.basename(MODEL),
                                     len(loaded.children)))
        '''The loaded object is a ``sceneGraph``: the root of the file.  Its
        ``children`` are the nodes to mount, which is what lets a file be put
        inside a scene of your own rather than becoming the whole of it.'''
        self.model = Transform(scale=(1.6, 1.6, 1.6),
                               children=list(loaded.children))
        self.spin = Transform(children=[self.model])
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.12, 0.13, 0.16)]),
            DirectionalLight(direction=(-0.4, -0.7, -0.6)),
            self.spin,
        ])

        '''A ``DEF`` name in the file is how its author labelled a node, and
        ``getDEF`` is how to get hold of one: the handle a program needs to
        change what the file describes.  Here it is the timer the file's own
        animation runs on, which the space bar stops and starts.'''
        self.timeSensor = loaded.getDEF('Pyramid01-TIMER')
        self.addEventHandler('keypress', name=' ', function=self.OnToggle)

        '''The file's animation runs itself; this is a second one, written in
        Python over the top of it, to show that the two compose -- the loaded
        scene is ordinary nodes and nothing about it is closed to a program.
        :doc:`Animating a transform <using_animation>` is the timer in
        detail.'''
        self.timer = Timer(duration=PERIOD, repeating=1)
        self.timer.addEventHandler('fraction', self.OnFraction)
        self.timer.register(self)
        self.timer.start()
        print(__doc__)

    def OnFraction(self, event):
        import math
        self.spin.rotation = (0, 1, 0, 2.0 * math.pi * event.fraction())

    def OnToggle(self, event):
        '''``enabled`` is the ``TimeSensor``'s own field: switching it off
        leaves the pyramid where it stood.  Writing a field of a loaded node
        is writing to the scene -- there is no separate copy to keep in
        step.'''
        if self.timeSensor is None:
            return
        self.timeSensor.enabled = not self.timeSensor.enabled
        print('the file\'s animation is %s'
              % ('running' if self.timeSensor.enabled else 'stopped',))


'''_What a .wrl file brings with it_

The format carries more than geometry, and the engine reads it as written:

* *Appearance and Material* -- diffuse, emissive, specular, shininess and
  transparency, and an ``ImageTexture`` beside them.
* *Lights* -- ``PointLight``, ``DirectionalLight`` and ``SpotLight``, with
  their own attenuation and radius.
* *Sensors and routes* -- ``TimeSensor`` and the interpolators, wired with
  ``ROUTE``, which is what makes a file animate itself.
* *Viewpoints* -- named cameras the viewer can step through.
* *Inline* -- another file, loaded where the node sits.

``oglc-view model.wrl`` opens one without writing a program;
:doc:`the viewer page </viewer>` is what else it does.
'''

if __name__ == "__main__":
    TestContext.ContextMainLoop()
