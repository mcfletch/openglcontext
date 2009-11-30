#! /usr/bin/env python
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.arrays import arange

from OpenGLContext.scenegraph.basenodes import *

class TestContext( BaseContext ):
    initialPosition = (0,0,100)
    viewportDimensions = (1024,768)
    def OnInit( self ):
        """Generate scenegraph and lorentz equation on load"""
        count = 10000
        points = lorentz( count )
        line = arange(0.0,1.0,1.0/float(count))
        line2 = line[::-1]
        coord = Coordinate(
            point = points,
        )
        color = Color(
            color = map(
                None,
                line,
                line2,
                [0]*len(line)
            ),
        )
        self.ps = PointSet(
            coord = coord,
            color = color,
        )
        self.ils = IndexedLineSet( coordIndex=range(len(points)), coord=coord, color=color )
        self.switch = Switch(
            whichChoice = 1,
            choice = [
                Shape(
                    geometry = self.ps
                ),
                Shape(
                    geometry = self.ils,
                ),
            ],
        )
        ts = TimeSensor( cycleInterval=300, loop=True )
        self.sg = sceneGraph(
            children = [
                Transform(
                    #scale = (.1,.1,.1), # it's pretty big without this, but makes it easier to walk around in
                    children = [
                        self.switch,
                    ],
                ),
                ts,
            ],
        )
        # register key 's' to switch rendering types...
        self.addEventHandler( "keypress", name="s", function = self.OnSwitch)
        
        print 'Should display a Lorentz Attractor'
        print '  s -- switch between IndexedLineset and Pointset presentation'
        timer = ts.getTimer( self )
        timer.addEventHandler( "fraction", function = self.OnTime )
    def OnTime( self, event ):
        count = int(event.fraction() * 100000)
        points = lorentz( count )
        count = len(points)
        line = arange(0.0,1.0,1.0/float(count+1))[:count]
        line2 = line[::-1]
        self.ps.coord.point = points
        self.ps.color.color = map(
            None,
            line,
            line2,
            [0]*len(line)
        )
        self.ils.coordIndex = range(len(points))



    def OnSwitch( self, event ):
        """Switch to alternate representation"""
        self.switch.whichChoice = (self.switch.whichChoice + 1)%len(self.switch.choice)
        self.triggerRedraw()

def lorentz( iterations = 100000, start=(0,-2,-1) ):
    """Calculate the lorentz equation"""
    h = 0.01
    a = 10.0
    b = 28.0
    c = 8.0/3.0
    x0,y0,z0 = start
    points = []
    for n in xrange( 0, iterations ):
        # lorentz linear function set
        x1 = x0 + h *  a *(y0-x0)
        y1 = y0 + h * (x0*(b-z0) - y0)
        z1 = z0 + h * (x0*y0 - c*z0)
        # solution becomes next seed
        x0 = x1
        y0 = y1
        z0 = z1
        points.append( (x0,y0,z0) )
    return points


if __name__ == "__main__":
    import sys, cProfile
    cProfile.run( "TestContext.ContextMainLoop()", 'OpenGLContext.profile' )