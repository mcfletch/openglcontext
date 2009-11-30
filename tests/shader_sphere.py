#! /usr/bin/env python
'''Shader sample-code for OpenGLContext
'''
import OpenGL 
#OpenGL.FULL_LOGGING = True
OpenGL.ERROR_ON_COPY = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGLContext.scenegraph.shaders import *
from OpenGLContext.scenegraph.basenodes import ImageTexture

def sphere( phi=pi/8.0, latAngle=pi, longAngle=(pi*2) ):
    """Create arrays for rendering a unit-sphere
    
    phi -- angle between points on the sphere (stacks/slices)
    
    Note: creates 'H' type indices...
    """
    latsteps = arange( 0,latAngle+0.000003, phi )
    longsteps = arange( 0,longAngle+0.000003, phi )
    return _partialSphere( latsteps,longsteps )

def _partialSphere( latsteps, longsteps ):
    """Create a partial-sphere data-set for latsteps and longsteps"""
    ystep = len(longsteps)
    zstep = len(latsteps)
    xstep = 1
    coords = zeros((zstep,ystep,5), 'f')
    coords[:,:,0] = sin(longsteps)
    coords[:,:,1] = cos(latsteps).reshape( (-1,1))
    coords[:,:,2] = cos(longsteps)
    coords[:,:,3] = longsteps/(2*pi)
    coords[:,:,4] = latsteps.reshape( (-1,1))/ pi
    
    # now scale by sin of y's 
    scale = sin(latsteps).reshape( (-1,1))
    coords[:,:,0] *= scale
    coords[:,:,2] *= scale
    
    indices = zeros( (zstep-1,ystep-1,6),dtype='H' )
    # all indices now render the first rectangle...
    indices[:] = (0,0+ystep,0+ystep+xstep, 0,0+ystep+xstep,0+xstep)
    xoffsets = arange(0,ystep-1,1,dtype='H').reshape( (-1,1))
    indices += xoffsets
    yoffsets = arange(0,zstep-1,1,dtype='H').reshape( (-1,1,1))
    indices += (yoffsets * ystep)
    
    # now optimize/simplify the data-set...
    new_indices = []
    
    for (i,iSet) in enumerate(indices ):
        angle = latsteps[i]
        nextAngle = latsteps[i+1]
        if allclose(angle%(pi*2),0):
            iSet = iSet.reshape( (-1,3))[::2]
        elif allclose(nextAngle%(pi),0):
            iSet = iSet.reshape( (-1,3))[1::2]
        else:
            iSet = iSet.reshape( (-1,3))
        new_indices.append( iSet )
    indices = concatenate( new_indices )
    return coords.reshape((-1,5)), indices.reshape((-1,))

class TestContext( BaseContext ):
    """OpenGL 3.1 deprecates non-vertex-attribute drawing
    
    This sample code shows how to draw geometry using VBOs
    and generic attribute objects, rather than using GL state
    to pass values.
    
    Each attribute within a compiled and linked program has 
    a "location" bound to it (similar to a uniform), the 
    location can be queried with a call go glGetAttribLocation
    and the location can be passed to the glVertexAttribPointer
    function to bind a particular data source (normally a 
    VBO, and only a VBO under OpenGL 3.1) to that attribute.
    """
    
    def OnInit( self ):
        coords,indices = sphere( pi/128, pi/2, pi*2 )
        coords = ascontiguousarray( coords )
        self.coordLength = len(indices)
        self.coords = vbo.VBO( coords )
        self.indices = vbo.VBO( indices, target = 'GL_ELEMENT_ARRAY_BUFFER' )
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        self.texture = ImageTexture( url = ["nehe_glass.bmp"] )
        
    
    def Render( self, mode = 0):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        self.texture.render( mode=mode )
        self.coords.bind()
        # TODO: use attributes rather than legacy operations...
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        glVertexPointer( 3, GL_FLOAT,20,self.coords)
        glTexCoordPointer( 3, GL_FLOAT,20,self.coords+12)
        glNormalPointer( GL_FLOAT,20,self.coords )
        self.indices.bind()
        # Can loop loading matrix and calling just this function 
        # for each sphere you want to render...
        # include both scale and position in the matrix...
        glDrawElements( GL_TRIANGLES, self.coordLength, GL_UNSIGNED_SHORT, self.indices )
        

if __name__ == "__main__":
    #import cProfile
    #cProfile.run( 'TestContext.ContextMainLoop()', 'sphere.profile' )
    TestContext.ContextMainLoop()

#	sphere( pi/4 )
    