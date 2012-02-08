#! /usr/bin/env python
"""Simple GLU Tess-object test w/out combine callback"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph import polygontessellator, vertex
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGLContext.arrays import *


outline = array([
    [191,   0],
    [ 191, 1480],
    [ 191, 1480],
    [ 401, 1480],
    [ 401, 1480],
    [401,   856],
    [401,   856],
    [1105,  856],
    [1105,  856],
    [1105, 1480],
    [1105, 1480],
    [1315, 1480],
    [1315, 1480],
    [1315,    0],
    [1315,    0],
    [1105,    0],
    [1105,    0],
    [1105,  699],
    [1105,  699],
    [401,   699],
    [401,   699],
    [401,     0],
    [401,     0],
    [191,     0],
    [191,     0],
    [191,     0],
], 'd')

class TestContext( BaseContext ):
    scale = 400.0
    def OnInit( self ):
        self.tess = polygontessellator.PolygonTessellator()
        glEnable( GL_COLOR_MATERIAL )
        
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glDisable( GL_LIGHTING )
        self.renderCap( self.scale )

    def renderCap( self, scale = 400.0):
        """The cap is generated with GLU tessellation routines...
        """
        vertices = [
            vertex.Vertex( (x/scale,y/scale,0) ) for (x,y) in outline[::2]
        ]
        vertices.reverse()
        for type, vertices in self.tess.tessellate( vertices, forceTriangles=0 ):
            glNormal( 0,0,-1 )
            glColor3f( 1,0,0 )
            glBegin( type )
            for v in vertices:
                glVertex2dv( v.point[:2] )
            glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
