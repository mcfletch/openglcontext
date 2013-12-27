#! /usr/bin/env python
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.arrays import *
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.arrays import vbo

class TestContext( BaseContext ):
    USE_VBO = True
    def OnInit( self ):
        a = arange( 0, 350000, dtype='i')
        self.geometry = b = zeros( (350000,3), dtype='f' )
        b[:,0] = sin( a ) *2
        b[:,1] = cos( a ) + (a/50000.).astype('f')
        self.start_indices = arange( 0, 350000, 7, dtype='i' )
        self.lengths = tile( array([7],dtype='i'), 50000 )
        if self.USE_VBO:
            self.geometry = vbo.VBO( self.geometry )
    def Render( self, mode=None, **named ):
        if mode.visible:
            self.render_geom()
    def render_geom( self ):
            try:
                if self.USE_VBO:
                    self.geometry.bind()
                glDisable( GL_LIGHTING )
                glColor3f( 0.,1.,0. )
                glEnableClientState( GL_VERTEX_ARRAY )
                glVertexPointerf( self.geometry )
                glMultiDrawArrays(
                    GL_LINE_STRIP,
                    self.start_indices,
                    self.lengths,
                    50000
                )
            finally:
                glDisableClientState( GL_VERTEX_ARRAY )
                glEnable( GL_LIGHTING )
                if self.USE_VBO:
                    self.geometry.unbind()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
