#! /usr/bin/env python
'''Test point parameter rendering code
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.arrays import *
from math import pi
import sys

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.events.timer import Timer
from OpenGL.GL import *
from OpenGL.GL.ARB.point_parameters import *

class TestContext( BaseContext ):
    initialPosition = (0,0,3) # set initial camera position, tutorial does the re-positioning
    usingExtension = True
    def OnInit( self ):
        """Load the image on initial load of the application"""
        haveExtension = self.extensions.initExtension( "GL.ARB.point_parameters")
        if not haveExtension:
            print 'GL_ARB_point_parameters not supported!'
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        print """Should see a sine wave overhead"""
        print 'press x toggle use of the extension'
        self.addEventHandler(
            'keypress', name = 'x', function = self.OnDisableExtension
        )
        
        line = arange(0.0,1.0,.01)
        line2 = line[::-1]
        self.coordinate = Coordinate(
            point = map(None, line,[0]*len(line), [0]*len(line) ),
        )
        self.color = Color(
            color = map(None,line, [0]*len(line), line2 ),
        )
        self.geometry = PointSet(
            coord = self.coordinate,
            color = self.color,
            size = 4.0,
            minSize = 0.25,
            maxSize = 4.0,
            attenuation = (0,0,1),
        )
        self.sg = sceneGraph(
            children = [
                Transform(
                    translation = (-.5,.25,0),
                    scale = (2,2,2),
                    rotation = (1,0,0,1.57),
                    children = [
                        Shape(
                            geometry = self.geometry,
                        ),
                    ],
                ),
            ],
        )
        self.time = Timer( duration = 8.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
    def OnTimerFraction( self, event ):
        """On event from the timer, generate new geometry"""
        xes = arange( 0.0, 1.0, 0.01 )
        range = (xes - event.fraction())*math.pi*2
        yes = sin( range )
        points = map(None,xes,yes,[0.0]*len(xes))
        colors = map(None,xes,xes[::-1],[0.0]*len(xes))
        self.coordinate.point = points
        self.color.color = colors
    def OnDisableExtension( self, event ):
        if self.usingExtension:
            self.geometry.attenuation = (1,0,0)
            self.usingExtension = False
            print 'attenuation:', self.geometry.attenuation
        else:
            self.geometry.attenuation = (0,0,1)
            self.usingExtension = True
            print 'attenuation:', self.geometry.attenuation
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
