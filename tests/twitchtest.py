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
        finally:
            self.twitch.vertex_vbo.unbind()
            glDisableClientState( GL_COLOR_ARRAY )
        verts,indices = self.twitch.patch_faces
        if indices:
            try:
                verts.bind()
                glEnableClientState( GL_VERTEX_ARRAY )
                glEnableClientState( GL_NORMAL_ARRAY )
                glEnableClientState( GL_TEXTURE_COORD_ARRAY )
                glVertexPointer(
                    3,GL_FLOAT,
                    verts.itemsize,
                    verts,
                )
                glNormalPointer(
                    GL_FLOAT,
                    verts.itemsize,
                    verts + (3*4),
                )
                glTexCoordPointer(
                    3,GL_FLOAT,
                    verts.itemsize,
                    verts + (6*4),
                )
                indices.bind()
                glDrawElements( 
                    GL_TRIANGLES, 
                    len(indices), 
                    GL_UNSIGNED_INT, 
                    indices, 
                )
            finally:
                verts.unbind()
                indices.unbind()

if __name__ == "__main__":
    logging.basicConfig( level = logging.WARN )
    TwitchContext.ContextMainLoop()
