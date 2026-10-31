#! /usr/bin/env python
'''= Using X3D/VRML Routing =

X3D and VRML97 have the ability to "wire together" events
and field updates between nodes with ROUTES. This allows
you to load an authored file that has built-in reactivity
or animations, for instance, you can route the same 
:py:class:`OpenGLContext.scenegraph.timesensor.TimeSensor`
to drive multiple animations at the same time.

When you load an X3D or VRML97 world, the routes in the world
will be automatically enabled.
'''
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.arrays import sin, cos, pi
import os

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.join(HERE, 'timesensor.wrl')

class TestContext( BaseContext ):
    """Context to load timesensor.wrl and watch routing changes

    The context loads the given file, looks up the Timer name
    in that file, and routes it to another handler.
    """
    '''Set up the camera and initial rotation.'''
    initialPosition = (0,0,10)
    rot = 6.283

    def OnInit( self ):
        """Load the scene on initial load of the application"""
        self.sceneLoader.load( WORLD,
                               on_loaded=self.OnLoaded )
    def OnLoaded( self, request ):
        """Mount the scene when the loader has read it"""
        self.sg = request.result
        '''Here we will add a new route to the world, wiring up two
        existing nodes to forward events. The `getDEF` method looks
        up the nodes in the world by their DEF name returning either
        the node or None.
        
        We'll take the TimeSensor named "Timer" and route its 
        fraction_changed to the LightOrient (OrientationInterpolator)
        set_fraction. The route in the world will then forward that
        to the rotation for the light.
        '''
        self.timer = self.sg.getDEF('Timer')
        self.light_orient = self.sg.getDEF('LightOrient')
        self.sg.addRoute(
            (
                self.timer,
                'fraction_changed',
                self.light_orient, 
                'set_fraction',
            )
        )
        '''We'll also demonstrate how to map an event or field change
        to a code handler. Your handler must be held by your
        context to avoid it being garbage-collected. Methods on objects
        are allowed as long as the object itself is not
        garbage-collected.'''
        self.background = self.sg.getDEF('Back')
        self.sg.addRoute(
            (
                self.timer,
                'fraction_changed',
                self.OnFraction,
            )
        )
    '''The receiver of the route needs to have (signal, sender, value)
    parameters.'''
    def OnFraction(self, signal, sender, value ):
        """Demonstrate handling a fraction changed"""
        '''This will cause the red and green channels of the background
        colour to smoothly oscillate between 0 and 1.0.'''
        self.background.color = (sin(value*pi),sin(value*pi),1.0)

if __name__ == "__main__":
    TestContext.ContextMainLoop(definition={
    })
