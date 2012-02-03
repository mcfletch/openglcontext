# -*- coding: latin-1 -*-
"""Simple GLU Tess-object test with combine callbacks"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGLContext.arrays import array


outline = [
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
]

class TestContext( BaseContext ):
    scale = 400.0
    def OnInit( self ):
        self.tess = gluNewTess()
        print 'Python-callback-using version of tessellation test'
        
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        # we get the tess'd geometry backward for some reason :(
        glDisable( GL_CULL_FACE )
        glEnable( GL_COLOR_MATERIAL )
        self.renderCap( self.scale )

    def renderCap( self, scale = 400.0):
        """The cap is generated with GLU tessellation routines...
        """
        gluTessCallback(self.tess, GLU_TESS_BEGIN, glBegin)
        def test( t, polyData=None ):
            glNormal( 0,0, -1 )
            glColor3f( t[0]/2.0,t[1]/2.0,t[2]/2.0 )
            return glVertex3f( t[0],t[1],t[2])
        gluTessCallback(self.tess, GLU_TESS_VERTEX_DATA, test)
        gluTessCallback(self.tess, GLU_TESS_END, glEnd);
        def combine( points, vertices, weights ):
            #print 'combine called', points, vertices, weights
            return points
        gluTessCallback(self.tess, GLU_TESS_COMBINE, combine)
        gluTessBeginPolygon( self.tess, None )
        try:
            gluTessBeginContour( self.tess )
            try:
                for (x,y) in outline:
                    vertex = array((x/scale,y/scale,0.0),'d')
                    gluTessVertex(self.tess, vertex, vertex)
            finally:
                gluTessEndContour( self.tess )
        finally:
            gluTessEndPolygon(self.tess)

if __name__ == "__main__":
    TestContext.ContextMainLoop()
