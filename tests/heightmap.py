#! /usr/bin/env python
'''Test/demo of heightmap rendering (array-based)'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array
from OpenGLContext.scenegraph.basenodes import *
try:
    from PIL import Image
except ImportError as err:
    import Image
from vrml import arrays

class TestContext( BaseContext ):
    # initialPosition/initialOrientation are set from the actual terrain
    # extents in OnInit (the heightmap image size decides how big the terrain
    # is, so a fixed viewpoint would frame the wrong volume).
    initialOrientation = (-1, 0, 0, 1.0)  # Pitch down ~57 degrees

    def OnInit( self ):
        """Initialisation"""
        print("""Should see a simplistic terrain (a height-mapped surface)""")
        points = Image.open( "heightmap.png" ).convert('L')
        print(points.format)
        ix,iy,data = points.size[0],points.size[1],points.tobytes()
        data = arrays.frombuffer( data, 'B' ).astype( 'f' )
        self.data = arrays.zeros( (ix,iy,3), 'f' )
        markers = arrays.swapaxes( arrays.indices( (ix,iy), 'f'), 0,2 )
        self.data[:,:,0] = markers[:,:,0]
        self.data[:,:,2] = markers[:,:,1]
        #self.data[:,:,2] = arrays.arange( 0,iy, dtype='f' ).reshape( (1,iy) )
        #self.data[:,:,0] = arrays.arange( 0,ix, dtype='f' )
        self.data[:,:,1] = data.reshape( (ix,iy) )
        # GL_QUAD_STRIP values (simple rendering)
        # If iy is not event this goes to heck!
        assert not iy%2, ("""Need a power-of-2 image for heightmap!""", iy)
        lefts = arrays.arange( 0, iy*(ix-1), dtype='I' )
        # create the right sides of the rectangles
        lrs = arrays.repeat( lefts, 2 )
        lrs[1::2] += iy 
        
        self.indices = lrs.reshape( (ix-1,iy*2) )
        
        self.shape = IndexedPolygons(
            polygonSides = GL_QUAD_STRIP,
            index = self.indices,
            coord = Coordinate(
                point = self.data,
            ),
            solid= False,
            normal = Normal(
                vector= array([0,1,0]*(ix*iy),'f'),
            ),
        )
        
        self.sg = sceneGraph(
            children = [
                Transform(
                    translation = (0,-10,0),
                    scale = (1.0, 0.002, 1),
                    children = [
                        Shape(
                            appearance = Appearance( material = Material(
                                diffuseColor = (.5,1,.5),
                            )),
                            geometry = self.shape,
                        ),
                    ],
                ),
                PointLight(
                    location=(10,8,5),
                ),
            ],
        )

        # Frame the terrain: it spans x in [0,ix-1], z in [0,iy-1] and sits at
        # y~-10 (Transform above). Sit above the centre and back along +z so the
        # pitched-down orientation looks straight at it. The view platform is
        # created before OnInit runs (its position can't be a class attribute
        # here because the terrain size isn't known until the image loads), so
        # move it directly now that we know the extents.
        span = max( ix, iy )
        self.initialPosition = ( (ix-1)/2.0, 8.0, (iy-1)/2.0 + span*0.8 )
        if self.platform is not None:
            self.platform.setPosition( self.initialPosition )
            self.platform.setOrientation( self.initialOrientation )

#    def Render( self, mode = None):
#        BaseContext.Render( self, mode )
#        # render the regular geometry 
#        if mode.visible:
#            #glDisable( GL_LIGHTING )
#            glEnable(GL_AUTO_NORMAL)
#            glEnable(GL_NORMALIZE)
#            glScalef( 1.0, 0.002, 1 )
#            glColor3f( .8,0,0)
#            glVertexPointerf( self.data )
#            glEnableClientState(GL_VERTEX_ARRAY);
#            for strip in self.indices:
#                glDrawElementsui(
#                    GL_QUAD_STRIP,
#                    strip
#                )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
