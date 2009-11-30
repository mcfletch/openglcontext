#! /usr/bin/env python
'''=Light Nodes, ROUTEs=

[lightobject.py-screen-0001.png Screenshot]
[lightobject.py-screen-0002.png Screenshot]
[lightobject.py-screen-0003.png Screenshot]


This tutorial creates a simple scenegraph that includes a number 
of light nodes that demonstrate some of the VRML97 light properties 
that OpenGLContext makes available.  It also demonstrates basic 
use of ROUTEs to create simple animations of properties within the 
scenegraph.

Note that the legacy OpenGL lighting model described here can be 
replaced when using shader-based geometry.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
'''We'll load the whole set of VRML97 base nodes and get the value 
of pi to some reasonable accuracy (from numpy).'''
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.arrays import pi
import random
'''You'll note that we haven't imported any OpenGL modules here,
the whole tutorial is accomplished with scenegraph nodes, rather than 
raw OpenGL rendering.'''

class TestContext( BaseContext ):
    angle = 0
    def OnInit( self ):
        """Load the image on initial load of the application"""
        print """You should see an opaque sphere and a translucent cylinder
with rotating lighting in three colours."""
        '''Each of the light types defined in VRML97 is going to be 
        defined for this tutorial.  Each of these lights includes 
        color, intensity, ambientIntensity and attenuation fields.
        These are pretty much passed directly into the underlying 
        (default) OpenGL lighting model.  The lights also have an 
        "on" field for turning them on/off.
        
        The DirectionalLight class represents the simplest type of 
        Light.  It is an "infinitely far off" light which sends 
        rays in parallel throughout the entire scene along its 
        "direction" vector.  It resembles the light cast by the 
        sun as seen on the surface of the Earth.
        '''
        dl = DirectionalLight(
            direction = (-10,-10,0),
            color= (0,1,0),
        )
        '''The PointLight is a slightly more complex light.  It is 
        a "point emitter", similar to an unshielded lightbulb or 
        candle, which sends rays out in all directions.  As such it 
        does not have a "direction" vector, but does have a location 
        vector.'''
        pl = PointLight(
            location = (-2,2,2),
            color=(1,0,0),
            radius = 3,
        )
        '''The SpotLight is the most complex light.  It resembles a 
        stage spotlight with a shield that restricts the light emitted 
        to a cone which is rooted at the light's location with "beamWidth" 
        angle.'''
        sl = SpotLight(
            location = (0,0,4),
            color = (0,0,1),
            direction = (0,0,-1),
        )
        '''We keep a reference to the light objects for later mutations'''
        self.lights = [
            dl,pl,sl,
        ]
        '''We are going to make our lights animate by rotating around the 
        center of this Transform node.  We give it a DEF name so that it 
        is easy to reference in later ROUTEs.'''
        self.lightTransform = Transform(
            DEF = 'Light-Transform',
            children = self.lights,
        )
        '''Here's where we define the key-frames for our animations.  
        The first animation defines a simple Orientation (rotation)
        around the Y-axis.  The second defines a "bounce" from 
        .25 to 1.0 to .25.  Note that we again define DEF values so 
        that we can reference the node easily in the future.
        
        The Timer node is what will generate the events we'll be using 
        to perform the animation.  Here we say that it will take 3.0s
        to complete a single cycle and that it will loop indefinitely 
        (a value of 1 means loop indefinitely, larger integers will loop 
        a specified number of times, 0 means do not loop).
        '''
        interpolators = [
            OrientationInterpolator(
                DEF = 'Light-Orient',
                key = [0,.25,.5,.75,1.0],
                keyValue = [
                    0,1,0,0, 
                    0,1,0,pi/2,  
                    0,1,0,pi, 
                    0,1,0,3*pi/2,  
                    0,1,0,0
                ],
            ),
            ScalarInterpolator(
                key = [0,.5,1],
                keyValue = [.25,1,.25],
                DEF = 'Intensity-Interp',
            ),
            TimeSensor(
                cycleInterval = 3.0,
                loop = True,
                DEF = 'Timer',
            ),
        ]
        '''Lights are only "visible" if there is geometry which is 
        going to be affected by them.  We define a very simplistic 
        scene with a Sphere, Teapot and transparent Cylinder.  The 
        Teapot and Cylinder are made very shiny so that the lighting 
        effects are more pronounced.
        '''
        geometry = [
            Shape(
                geometry = Sphere(
                ),
                appearance = Appearance(
                    material = Material( diffuseColor=(1,1,1) ),
                ),
            ),
            Transform(
                translation = (-3,-.25,1.5),
                rotation = (0,1,0,.75),
                children = [
                    Shape( 
                        geometry = Teapot( size=1.5 ),
                        appearance = Appearance(
                            material = Material(
                                shininess = .9,
                                diffuseColor = (.3,.3,.3),
                                specularColor = (1,1,0),
                            ),
                        ),
                    ),
                ],
            ),
            Transform(
                translation = (1,-.5,2),
                rotation = (1,0,0,.5),
                children = [
                    Shape(
                        geometry = Cylinder(
                        ),
                        appearance = Appearance(
                            material = Material(
                                diffuseColor=(1,1,1),
                                shininess = .8,
                                transparency = .3,
                            ),
                        ),
                    ),
                ],
            ),
        ]
        '''And here we actually put it all together into a scenegraph 
        that the Context will render.'''
        self.sg = sceneGraph(
            children = [
                self.lightTransform,
            ] + geometry + interpolators,
        )
        '''Our light-location animation is trivial to set up,
        we simply route the "fraction_changed" event of the Timer into 
        the "set_fraction" event of the Interpolator and then route the 
        "value_changed" event of the interpolator to the "set_rotation"
        event of the Transform which holds our lights.'''
        self.sg.addRoute( 
            'Timer','fraction_changed',
            'Light-Orient','set_fraction' 
        )
        self.sg.addRoute( 
            'Light-Orient','value_changed',
            'Light-Transform','set_rotation' 
        )
        '''Our light-intensity animation is similar to the Orientation
        interpolation we performed above, but instead of routing the 
        "value_changed" value to a Node, we route it to a method which 
        can do as it likes with the value.  In this case our method 
        just applies the value to each Node.  We could also have 
        routed the value_changed event to each light's set_intensity 
        event with the same effect.
        '''
        self.sg.addRoute( 
            'Timer','fraction_changed',
            'Intensity-Interp','set_fraction' 
        )
        self.sg.addRoute( 
            'Intensity-Interp','value_changed',
            self.onIntensity
        )
        '''Here again we are going to take an event and route it to 
        a function.  However, here we take an event directly from 
        the Timer node and route it to our method.  The "cycleTime"
        event is sent each time the Timer completes a cycle, so here 
        it will be called every 3s to decide randomly to turn off/on 
        the lights in the scene.
        '''
        self.sg.addRoute(
            'Timer','cycleTime', 
            self.onCycle,
        )
    '''Our event handlers, as discussed above.'''
    def onCycle( self, **named ):
        for light in self.lights:
            if random.random() > .6:
                light.on = False 
            else:
                light.on = True
    def onIntensity( self, value ):
        for light in self.lights:
            light.intensity = value 

if __name__ == "__main__":
    TestContext.ContextMainLoop()
