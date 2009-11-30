#! /usr/bin/env python
'''Test/demo of heightmap rendering (array-based)'''

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string
try:
    from PIL import Image
except ImportError, err:
    import Image
import flower_geometry
from vrml import arrays

class TestContext( BaseContext ):
    def OnInit( self ):
        """Initialisation"""
        print """Should see a simplistic terrain"""
        points = Image.open( "heightmap.png" ).convert('L')
        print points.format
        ix,iy,data = points.size[0],points.size[1],points.tostring()
        data = arrays.frombuffer( data, 'b' ).astype( 'f' )
        self.data = arrays.zeros( (ix,iy,3), 'f' )
        markers = arrays.swapaxes( arrays.indices( (ix,iy), 'f'), 0,2 )
        self.data[:,:,0] = markers[:,:,0]
        self.data[:,:,2] = markers[:,:,1]
        #self.data[:,:,2] = arrays.arange( 0,iy, dtype='f' ).reshape( (1,iy) )
        #self.data[:,:,0] = arrays.arange( 0,ix, dtype='f' )
        self.data[:,:,1] = data.reshape( (ix,iy) )
        print 'left corner', self.data[:10,:10,:]
        # GL_QUAD_STRIP values (simple rendering)
        # If iy is not event this goes to heck!
        assert not iy%2, ("""Need a power-of-2 image for heightmap!""", iy)
        lefts = arrays.arange( 0, iy*(ix-1), dtype='I' )
        # create the right sides of the rectangles
        lrs = arrays.repeat( lefts, 2 )
        lrs[1::2] += iy 
        
        self.indices = lrs.reshape( (ix-1,iy*2) )
        
    def Render( self, mode = None):
        BaseContext.Render( self, mode )
        # render the regular geometry 
        if mode.visible:
            #glDisable( GL_LIGHTING )
            glEnable(GL_AUTO_NORMAL)
            glEnable(GL_NORMALIZE)
            glScalef( 1.0, 0.002, 1 )
            glColor3f( .8,0,0)
            glVertexPointerf( self.data )
            glEnableClientState(GL_VERTEX_ARRAY);
            for strip in self.indices:
                glDrawElementsui(
                    GL_QUAD_STRIP,
                    strip
                )



if __name__ == "__main__":
    TestContext.ContextMainLoop()