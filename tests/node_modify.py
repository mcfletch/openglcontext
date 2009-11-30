#! /usr/bin/env python
"""Test of routing the modification of one node to another"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
import os, sys
from OpenGLContext.events.timer import Timer
try:
    from OpenGLContext.loaders.loader import Loader
except ImportError, err:
    print """This demo requires the VRML97 loader"""

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
        print """This demo loads a VRML97 scenegraph and modifies
the rotation of the transform which contains one of the two boxes.
The ROUTE in the scene transmits this rotational change to the
transform which contains the other box."""
        self.sg = Loader.load( os.path.join("wrls","box.wrl") )
        self.trans = self.sg.getDEF( "Box01" )
        self.time = Timer( duration = 8.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
    def OnTimerFraction( self, event ):
        """Modify the node"""
        x,y,z,r = self.trans.rotation
        self.trans.rotation = x,y,z,(self.rot*event.fraction())

if __name__ == "__main__":
    TestContext.ContextMainLoop()