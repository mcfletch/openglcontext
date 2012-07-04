"""Renderer for a Twitch node (Quake III style BSP map)"""
import logging,numpy, sys
from OpenGLContext import testingcontext
from OpenGLContext.loaders import twitch
from OpenGL.GL import *
BaseContext = testingcontext.getInteractive()

class TwitchContext( BaseContext ):
#    initialPosition = (-432.,-336., -736.)
#    initialPosition = (304.,  568., -696)
#    initialPosition = -120., -576., -480.
    
    def OnInit( self ):
        self.twitch = twitch.load( sys.argv[1] )
        # okay, load up the various vbo
        self.twitch.patch_faces
        
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glScalef( .01, .01, .01 )
        glDisable(GL_LIGHTING)
        glDisable(GL_CULL_FACE)
        self.twitch.vertex_vbo.bind()
        try:
            glEnableClientState( GL_VERTEX_ARRAY )
            glEnableClientState( GL_COLOR_ARRAY )
            glVertexPointer(
                3,GL_FLOAT,
                self.twitch.vertex_vbo.itemsize,
                self.twitch.vertex_vbo,
            )
            glColorPointer(
                3,GL_FLOAT,
                self.twitch.vertex_vbo.itemsize,
                self.twitch.vertex_vbo + (40),
            )
            self.twitch.simple_faces.bind()
            try:
                glDrawElements( 
                    GL_TRIANGLES, 
                    len(self.twitch.simple_faces), 
                    GL_UNSIGNED_INT, 
                    self.twitch.simple_faces 
                )
            finally:
                self.twitch.simple_faces.unbind()
            self.twitch.patch_faces.bind()
            try:
                glDrawElements( 
                    GL_TRIANGLES, 
                    len(self.twitch.patch_faces), 
                    GL_UNSIGNED_INT, 
                    self.twitch.patch_faces 
                )
            finally:
                self.twitch.patch_faces.unbind()
        finally:
                self.twitch.vertex_vbo.unbind()

if __name__ == "__main__":
    logging.basicConfig( level = logging.WARN )
    TwitchContext.ContextMainLoop()
