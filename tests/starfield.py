#! /usr/bin/env python
'''PointSet object test (draw line of coloured dots)
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.arrays import *
from math import pi
from numpy import random

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.events.timer import Timer

class TestContext( BaseContext ):
    def OnInit( self ):
        """Load the image on initial load of the application"""
        print """Should see a rotating star-field"""
        starfield = random.rand( 9110, 3 )
        self.coordinate = Coordinate(
            point = starfield,
        )
        self.color = Color(
            color = starfield,
        )
        self.transform = Transform(
            scale = (200,200,200),
            children = [
                Transform(
                    translation=(-.5,-.5,-.5),
                    children=[
                        Shape(
                            geometry = PointSet(
                                coord = self.coordinate,
                                color = self.color,
                            ),
                        ),
                    ],
                ),
            ],
        )
        self.sg = sceneGraph(
            children = [
                self.transform,
            ],
        )
        self.time = Timer( duration = 90.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
    def OnTimerFraction( self, event ):
        """On event from the timer, generate new geometry"""
        self.transform.rotation = (0,1,0,2*math.pi * event.fraction() )
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
