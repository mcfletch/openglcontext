#! /usr/bin/env python
'''Test of the glDrawElements function taken from a list'''
import sys
if sys.argv[1:]:
    import OpenGL 
    OpenGL.ERROR_ON_COPY = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string
import flower_geometry

class TestContext( BaseContext ):
    useArrays = 0
    colors = [(1,0,0),(0,0,.75)]
    def OnInit( self ):
        """Initialisation"""
        print """Should see a 2x2 box in red on white"""
        self.addEventHandler( "keypress", name="a", function = self.OnUseArrays)
        print """  Press "a" to switch to using arrays"""
    def OnUseArrays( self, event=None ):
        """Toggle the use of Numeric arrays"""
        self.useArrays = not self.useArrays
        self.color = self.useArrays
        print "Using arrays?", ['No, box should be red.','Yes, box should be blue.'][self.useArrays]
        self.triggerRedraw()
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glColor( *self.colors[self.useArrays])
        glDisable( GL_LIGHTING )
        # following is required, the indices are in
        # CW, rather than default CCW order...
        glDisable( GL_CULL_FACE )
        VertexArray=[
            [0,0,0],[1,0,0],[2,0,0],
            [0,1,0],[1,1,0],[2,1,0],
            [0,2,0],[1,2,0],[2,2,0]
        ]
        IndiceArray=[
            0,3,4,
            0,4,1,
            1,4,5,
            1,5,2,
            3,6,7,
            3,7,4,
            4,7,8,
            4,8,5
        ]
        if self.useArrays:
            VertexArray=array(VertexArray, 'f')    #Here's the problem line
            IndiceArray=array(IndiceArray, 'I')
        glVertexPointerf(VertexArray)
        glEnableClientState(GL_VERTEX_ARRAY);
        glDrawElementsui(
            GL_TRIANGLES,
            IndiceArray
        )

if __name__ == "__main__":
    TestContext.ContextMainLoop()