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
        
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        self.renderCap( self.scale )

    def renderCap( self, scale = 400.0):
        """The cap is generated with GLU tessellation routines...
        """
        vertices = [
            vertex.Vertex( (x/scale,y/scale,0) ) for (x,y) in outline[::2]
        ]
        vertices.reverse()
        for type, vertices in self.tess.tessellate( vertices, forceTriangles=0 ):
#			print ' geometry type %s, %s vertices (GL_TRIANGLES=%s GL_TRIANGLE_FAN=%s GL_TRIANGLE_STRIP=%s)'%(
#				type,
#				len(vertices),
#				GL_TRIANGLES, GL_TRIANGLE_FAN, GL_TRIANGLE_STRIP
#			)
            glNormal( 0,0,-1 )
            glBegin( type )
            for v in vertices:
                glVertex2dv( v.point[:2] )
            glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()