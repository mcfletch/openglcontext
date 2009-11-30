#! /usr/bin/env python
'''Test of the glInterleavedArrays function (draws two quads)'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array

class TestContext( BaseContext ):
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glTranslatef( 1,0,0)
        
        vertices = array([ 
            0.0, 0.0, 0.0, 
            1.0, 0.0, 0.0, 
            1.0, 1.0, 0.0,
            0.0, 1.0, 0.0 
        ], 'f')
        indices = array([2, 3, 0, 1 ],'I')
        glInterleavedArrays(
            GL_V3F, # 3 vertex floats/item
            0, # tight packing
            vertices.tostring(),
        )
        glDrawElementsui(GL_QUADS,indices)

        glTranslatef( 0,-2,0)
        vertices = array([
            0,0,1,	0.0, 0.0, 0.0,	
            0,0,1,	1.0, 0.0, 0.0,	
            0,0,1,	1.0, 1.0, 0.0,	
            0,0,1,	0.0, 1.0, 0.0,	
        ], 'f')
        
        glInterleavedArrays(
            GL_N3F_V3F, # 3 vertex floats/item, 3 normals/item
            0, # tight packing
            vertices.tostring(),
        )
        glDrawElementsui(GL_QUADS, indices)
    def OnInit( self ):
        """Print welcome message"""
        print """You should see two squares one on top of the other 

The first is drawn with the GL_V3F variant, the second with the 
GL_N3F_V3F variant."""




if __name__ == "__main__":
    TestContext.ContextMainLoop()
