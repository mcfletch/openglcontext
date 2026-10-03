#! /usr/bin/env python
'''=Loading a VRML97 model=

[using_vrml97.py-screen-0001.png Screenshot]

OpenGLContext's native scenegraph is based on the VRML97 scenegraph,
and it includes support for loading VRML97 scenes. The 
:py:mod:`OpenGLContext.basenodes` module has the common VRML97 nodes
defined, and these are available to load from a VRML97 formatted
file (a .wrl file).

Content authored in VRML97 is relatively rare these days, but you
can load it in essentially the same way as you would load a glTF scene.
'''
import os

from OpenGLContext import testingcontext
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, Transform, sceneGraph,
    ColorInterpolator,
)

from OpenGLContext.context import Context as BaseContext

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
        '''Every context has a ``sceneLoader``, the one entry point for every
        format the engine reads.  ``load`` takes a path or a URL, chooses the
        reader for it from the name, and reads it on a worker thread so the
        window goes on drawing; ``OnLoaded`` is called on the render thread
        when the scene is ready.'''
        self.timeSensor = None
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.12, 0.13, 0.16)]),
            DirectionalLight(direction=(-0.4, -0.7, -0.6)),
        ])
        self.sceneLoader.load(MODEL, on_loaded=self.OnLoaded)
        self.addEventHandler('keypress', name=' ', function=self.OnToggle)
        print(__doc__)

    def OnLoaded(self, request):
        '''For a VRML97 world, the result of the request is a sceneGraph
        node. To render the world as-is you can assign it to `self.sg`.
        You can also pull nodes out of the sceneGraph's children and
        add them to your own sceneGraph.
        '''
        loaded:sceneGraph = request.result
        '''The loaded object is a ``sceneGraph``: the root of the file.  Its
        ``children`` are the nodes to mount, which is what lets a file be put
        inside a scene of your own rather than becoming the whole of it.'''
        self.sg = loaded
        '''As with glTF we can pull a particular node out of the scenegraph
        in order to modify it.'''
        self.timeSensor = loaded.getDEF('Pyramid01-TIMER')
        self.pyramidMaterial = loaded.getDEF('Pyramid01-Material')

        colorInterpolator = ColorInterpolator(
            keyValue=[1,0,0, 0,1,0, 0,0,1, 0,1,0, 1,0,0],
            key=[0,.25,.5,.75,1.0],
        )
        self.sg.children.append(colorInterpolator)
        self.sg.addRoute(
            (self.timeSensor,'fraction_changed',colorInterpolator,'set_fraction'),
        )
        self.sg.addRoute(
            (colorInterpolator,'value_changed',self.pyramidMaterial,'set_diffuseColor'),
        )

    def OnToggle(self, event):
        '''``enabled`` is the ``TimeSensor``'s own field: switching it off
        leaves the pyramid where it stood.  Writing a field of a loaded node
        is writing to the scene -- there is no separate copy to keep in
        step.'''
        if self.timeSensor is None:
            return
        self.timeSensor.enabled = not self.timeSensor.enabled


'''_What a .wrl file brings with it_

The format carries more than geometry, and the engine reads it as written:

* Appearance and Material - diffuse, emissive, specular, shininess and
  transparency, and an ``ImageTexture`` beside them.
* Lights - ``PointLight``, ``DirectionalLight`` and ``SpotLight``, with
  their own attenuation and radius.
* Sensors and routes - ``TimeSensor`` and the interpolators, wired with
  ``ROUTE``, which is what makes a file animate itself.
* Viewpoints - named cameras the viewer can step through.
* Inline - another file, loaded where the node sits.

``oglc-view model.wrl`` opens one without writing a program;
:doc:`the viewer page </viewer>` is what else it does.
'''

if __name__ == "__main__":
    TestContext.ContextMainLoop()
