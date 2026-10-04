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
VRML97 includes a lot of "scene authoring" features, such as sensors,
routes, interpolators and the like, and many will work out of the
box in OpenGLContext.
'''
import os

'''As before, we get the Context class as our Base'''
from OpenGLContext.context import Context as BaseContext
'''We import the scenegraph nodes we're going to use to customise
the world we are loading.'''
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
    ColorInterpolator,
)
'''This tiny test-file is sitting in the tests/wrls directory next
to this tutorial source. It's about 50 lines of plain text, with
the bulk of it being lists of numbers that make up the interpolator
data.

At the bottom of the file you'll see a number of ROUTEs which are
what wire up the animations in the world::

    ROUTE Pyramid01-TIMER.fraction_changed TO Pyramid01-POS-INTERP.set_fraction
    ROUTE Pyramid01-POS-INTERP.value_changed TO Pyramid01.set_translation

those routes feed the TimeSensor node's fraction_changed, which is
a continuously varying floating point number from 0=>1.0 that cycles
every period seconds. They then take the position output from the 
position interpolator and assign it to the translation applied to
the pyramid.
'''
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, 'wrls', 'positioninterpolator.wrl')

class TestContext(BaseContext):
    initialPosition = (0, 1.1, 4.2)
    initialOrientation = (-1, 0, 0, 0.12)

    def OnInit(self):
        """Initialise the context, kicking off any processes that need to run"""
        '''As with the glTF tutorial, we'll be using the `sceneLoader` member
        to load the actual content on a background thread. The sceneLoader will
        load the file we specified and arrange to call our on_loaded callback
        in the render thread when it's done.
        '''
        self.timeSensor = None
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.12, 0.13, 0.16)]),
            DirectionalLight(direction=(-0.4, -0.7, -0.6)),
        ])
        self.sceneLoader.load(MODEL, on_loaded=self.OnLoaded)
        '''Custom scene behaviour, when you press the space key we will 
        toggle the timesensor in the world enabled/disabled. When it is
        disabled it will pause, and when re-enabled it will continue from
        where it left off.
        '''
        self.addEventHandler('keypress', name=' ', function=self.OnToggle)

    def OnLoaded(self, request):
        '''For a VRML97 world, the result of the request is a sceneGraph
        node. To render the world as-is you can assign it to `self.sg`.
        You can also pull nodes out of the sceneGraph's children and
        add them to your own sceneGraph.
        '''
        loaded:sceneGraph = request.result
        '''The sceneGraph you get from a VRML97 loader can be directly
        assigned to `self.sg` on the context to load the world as authored.
        '''
        self.sg = loaded
        '''As with glTF we can pull a particular node out of the scenegraph
        in order to modify or animate it.
        
        We're going to grab the TimeSensor and the Material of the Pyramid.
        In VRML97, as with most formats, there are nodes that are named,
        and nodes that are not. We've modified the original file to add a 
        DEF name to the Material here so that it's easier to get a hold of.
        We could have, instead, pulled out a parent and walked down the path
        of node attributes to find the Material if we didn't want to modify
        the original file.
        '''
        self.timeSensor = loaded.getDEF('Pyramid01-TIMER')
        self.pyramidMaterial = loaded.getDEF('Pyramid01-Material')
        '''A ColorInterpolator is a node that converts a floating point
        value into a lookup across a linear interpolation of colours
        through a set of waypoint colours.
        
        In this example, we start at red, then green, then blue, then
        green again,then red again, each colour keyed at .25 past the
        last value. The result is a colour that cycles back and forth
        from red to blue and back through green each time.
        '''
        colorInterpolator = ColorInterpolator(
            keyValue=[1,0,0, 0,1,0, 0,0,1, 0,1,0, 1,0,0],
            key=[0,.25,.5,.75,1.0],
        )
        '''You need to add your nodes to the scenegraph they are part of
        in order for them to be properly registered and become active.'''
        self.sg.children.append(colorInterpolator)
        '''We add two new ROUTEs that forward the fraction from the timer
        and forward the colour from the interpolator to the material. These
        are the same structure as the statically declared ROUTE we noted
        in the VRML97 file.
        '''
        self.sg.addRoute(
            (self.timeSensor,'fraction_changed',colorInterpolator,'set_fraction'),
        )
        self.sg.addRoute(
            (colorInterpolator,'value_changed',self.pyramidMaterial,'set_diffuseColor'),
        )

    def OnToggle(self, event):
        """Handle request to toggle the TimeSensor"""
        '''Time in VRML97 is linked to a TimeSensor, and there can be many
        different TimeSensors in a complex world, often authored as one sensor
        for every animation. In this very simple world we've only got a 
        single TimeSensor, so when we toggle it on/off the entire world
        will stop animating.
        '''
        if self.timeSensor is None: # not yet loaded
            return
        self.timeSensor.enabled = not self.timeSensor.enabled

if __name__ == "__main__":
    TestContext.ContextMainLoop(definition={
        # the default renderer (pbr) would work fine,
        # but it tends to make vrml97 scenes look different 
        # enough that you likely want to use the pyvrml97
        # renderer if you actually want to view VRML97 scenes
        # as they were authored
        'renderer': 'pyvrml97',
    })

'''You can now run your Context from the command like like so::

    $ uv run --pre --with OpenGLContext python ./using_vrml97.py
'''