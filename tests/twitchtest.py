"""Renderer for a Twitch node (Quake III style BSP map)"""
import logging,numpy, sys
from OpenGLContext import testingcontext
from OpenGLContext.loaders import twitch
from OpenGL.GL import *
from OpenGL.arrays import vbo
BaseContext = testingcontext.getInteractive()

class TwitchContext( BaseContext ):
    def OnInit( self ):
        self.twitch = twitch.load( sys.argv[1] )
        self.simple_vertices = vbo.VBO( self.twitch.vertices )
        self.simple_indices = vbo.VBO( self.twitch.simple_faces, target=GL_ELEMENT_ARRAY_BUFFER )
        vertices,indices = self.twitch.patch_faces
        if indices is not None:
            self.patch_vertices = vbo.VBO( vertices )
            self.patch_indices = vbo.VBO( indices, target=GL_ELEMENT_ARRAY_BUFFER )
        else:
            self.patch_indices = None
        
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glScalef( .01, .01, .01 )
        glEnable(GL_LIGHTING)
        glEnable(GL_CULL_FACE)
        self.simple_vertices.bind()
        try:
            glEnableClientState( GL_VERTEX_ARRAY )
            glEnableClientState( GL_COLOR_ARRAY )
            glEnableClientState( GL_NORMAL_ARRAY )
            glVertexPointer(
                3,GL_FLOAT,
                self.simple_vertices.itemsize, # compound structure
                self.simple_vertices,
            )
            glNormalPointer(
                GL_FLOAT,
                self.simple_vertices.itemsize,
                self.simple_vertices + (3*4),
            )
            glColorPointer(
                3,GL_FLOAT,
                self.simple_vertices.itemsize,
                self.simple_vertices + (40),
            )
            self.simple_indices.bind()
            try:
                glDrawElements( 
                    GL_TRIANGLES, 
                    len(self.simple_indices), 
                    GL_UNSIGNED_INT, 
                    self.simple_indices 
                )
            finally:
                self.simple_indices.unbind()
        finally:
            self.simple_vertices.unbind()
            glDisableClientState( GL_COLOR_ARRAY )
        if self.patch_indices is not None:
            glEnable( GL_LIGHTING )
            glEnable( GL_CULL_FACE )
            try:
                self.patch_vertices.bind()
                glEnable( GL_LIGHTING )
                glEnableClientState( GL_VERTEX_ARRAY )
                glEnableClientState( GL_NORMAL_ARRAY )
                glEnableClientState( GL_TEXTURE_COORD_ARRAY )
                stride = self.patch_vertices.itemsize * self.patch_vertices.shape[-1]
                glVertexPointer(
                    3,GL_FLOAT,
                    stride,
                    self.patch_vertices,
                )
                glNormalPointer(
                    GL_FLOAT,
                    stride,
                    self.patch_vertices + (3*self.patch_vertices.itemsize),
                )
                glTexCoordPointer(
                    3,GL_FLOAT,
                    stride,
                    self.patch_vertices + (6*self.patch_vertices.itemsize),
                )
                try:
                    self.patch_indices.bind()
                    glDrawElements( 
                        GL_TRIANGLES, 
                        len(self.patch_indices), 
                        GL_UNSIGNED_INT, 
                        self.patch_indices, 
                    )
                finally:
                    self.patch_indices.unbind()
            finally:
                self.patch_vertices.unbind()

if __name__ == "__main__":
    logging.basicConfig( level = logging.WARN )
    TwitchContext.ContextMainLoop()
