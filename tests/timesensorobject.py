#! /usr/bin/env python
"""Test of routing the modification of one node to another"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
import os, sys
from OpenGLContext.events.timer import Timer
from OpenGLContext.loaders.loader import Loader

class TestContext( BaseContext ):
    """Context to load wrls/box.wrl and watch routing changes

    The context loads the given file, gets a pointer to a
    particular node within the file, then modifies that node's
    rotation field. The routes in the file forward the changes
    to another node, causing both boxes on-screen to rotate.
    """
    initialPosition = (0,0,10)
    rot = 6.283
    def OnInit( self ):
        """Load the image on initial load of the application"""
        self.sg = Loader.load( os.path.join("wrls","timesensor.wrl") )
##		self.trans = self.sg.getDEF( "Box01" )
##		self.timesensor = self.sg.getDEF( "Timer" )
##		timer = self.timesensor.getTimer( self )
##		timer.addEventHandler( "fraction", function = self.OnTimerFraction )
    def OnTimerFraction( self, event ):
        """Modify the node"""
        x,y,z,r = self.trans.rotation
        self.trans.rotation = x,y,z,(self.rot*event.fraction())
    


if __name__ == "__main__":
    TestContext.ContextMainLoop()


