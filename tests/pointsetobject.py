#! /usr/bin/env python
'''PointSet object test (draw line of coloured dots)
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.arrays import *
from math import pi

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.events.timer import Timer

class TestContext( BaseContext ):
    initialPosition = (0,0,3) # set initial camera position, tutorial does the re-positioning
    def OnInit( self ):
        """Load the image on initial load of the application"""
        print """Should see a sine wave fading from green to red"""
        line = arange(0.0,1.0,.01)
        line2 = line[::-1]
        self.coordinate = Coordinate(
            point = map(None, line,[0]*len(line), [0]*len(line) ),
        )
        self.color = Color(
            color = map(None,line, [0]*len(line), line2 ),
        )
        self.sg = sceneGraph(
            children = [
                Transform(
                    translation = (-.5,0,0),
                    children = [
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
        self.time = Timer( duration = 8.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
    def OnTimerFraction( self, event ):
        """On event from the timer, generate new geometry"""
        xes = arange( 0.0, 1.0, 0.005 )
        range = (xes - event.fraction())*math.pi*2
        yes = sin( range )
        points = map(None,xes,yes,[0.0]*len(xes))
        colors = map(None,xes,xes[::-1],[0.0]*len(xes))
        self.coordinate.point = points
        self.color.color = colors
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
