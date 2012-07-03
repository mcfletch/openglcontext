"""Renderer for a Twitch node (Quake III style BSP map)"""
import logging,numpy
from OpenGLContext import testingcontext
from OpenGLContext.loaders import twitch
from OpenGL.arrays import vbo
from OpenGL.GL import *
BaseContext = testingcontext.getInteractive()

class TwitchContext( BaseContext ):
    initialPosition = (-432.,-336., -736.)
    def OnInit( self ):
        self.twitch = twitch.load( '/home/mcfletch/OpenGL-dev/twitch/maps/focal_p132.bsp' )
        # okay, load up the various vbo
        self.vertices = vbo.VBO( self.twitch.vertices )
        faces = self.twitch.faces
        # for type 1 and 3 we can simply create indices...
        simple_types = numpy.logical_or( self.twitch.faces['type'] == 1, self.twitch.faces['type'] == 3)
        simple_faces = numpy.compress( simple_types, self.twitch.faces )
        simple_index_count = numpy.sum( simple_faces['n_meshverts'] )
        indices = numpy.zeros( (simple_index_count,), 'I4' )
        # ick, should be a fast way to do this...
        starts = simple_faces['meshvert']
        stops = simple_faces['meshvert'] + simple_faces['n_meshverts']
        start_indices = simple_faces['vertex']
        current = 0
        for start,stop,index in zip(starts,stops,start_indices):
            end = current + (stop-start)
            indices[current:end] = self.twitch.meshverts[start:stop] + index
        self.indices = vbo.VBO( indices, target = 'GL_ELEMENT_ARRAY_BUFFER' )
        # for type 2, we need to convert a control surface to a set of indices...
        
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glDisable(GL_LIGHTING)
        glDisable(GL_CULL_FACE)
        self.vertices.bind()
        self.indices.bind()
        print self.twitch.vertices['position']
        try:
            glEnableClientState( GL_VERTEX_ARRAY )
            glColor3f( 1.0,0,0 )
            glVertexPointer(
                3,GL_FLOAT,
                self.twitch.vertices.itemsize,
                self.vertices,
            )
            glDrawElements( GL_TRIANGLES, len(self.indices), GL_UNSIGNED_INT, self.indices )
        finally:
            self.vertices.unbind()
            self.indices.unbind()

if __name__ == "__main__":
    logging.basicConfig( level = logging.WARN )
    TwitchContext.ContextMainLoop()
