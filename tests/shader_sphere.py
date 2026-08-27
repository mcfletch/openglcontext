#! /usr/bin/env python
'''Shader sample-code for OpenGLContext

Draws a textured unit-sphere from one interleaved VBO through generic vertex
attributes.
'''
import OpenGL
#OpenGL.FULL_LOGGING = True
OpenGL.ERROR_ON_COPY = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders as gl_shaders
from OpenGLContext.scenegraph.shaders import *
from OpenGLContext.scenegraph.basenodes import ImageTexture

VERTEX_SHADER = """#version 330 core
uniform mat4 modelViewProjection;
in vec3 Vertex_position;
in vec2 Vertex_texture_coordinate;
out vec3 baseNormal;
out vec2 texCoord;
void main() {
    // A unit sphere's surface normal is its position.
    baseNormal = normalize( Vertex_position );
    texCoord = Vertex_texture_coordinate;
    gl_Position = modelViewProjection * vec4( Vertex_position, 1.0 );
}"""

FRAGMENT_SHADER = """#version 330 core
uniform sampler2D diffuse_texture;
uniform vec3 light_direction;
in vec3 baseNormal;
in vec2 texCoord;
out vec4 fragColor;
void main() {
    float diffuse = max( 0.0, dot( normalize(baseNormal), light_direction ) );
    vec4 colour = texture( diffuse_texture, texCoord );
    fragColor = vec4( colour.rgb * (0.25 + 0.75*diffuse), colour.a );
}"""

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
        self.texture = ImageTexture( url = ["nehe_glass.bmp"] )
        self.shader = gl_shaders.compileProgram(
            gl_shaders.compileShader( VERTEX_SHADER, GL_VERTEX_SHADER ),
            gl_shaders.compileShader( FRAGMENT_SHADER, GL_FRAGMENT_SHADER ),
        )
        self.position_location = glGetAttribLocation(
            self.shader, 'Vertex_position'
        )
        self.texcoord_location = glGetAttribLocation(
            self.shader, 'Vertex_texture_coordinate'
        )
        self.matrix_location = glGetUniformLocation(
            self.shader, 'modelViewProjection'
        )
        self.texture_location = glGetUniformLocation(
            self.shader, 'diffuse_texture'
        )
        self.light_location = glGetUniformLocation(
            self.shader, 'light_direction'
        )
        # The vertex array object into which the two attribute pointers are
        # recorded; there is no array state outside one.
        self.vao = glGenVertexArrays( 1 )

    def Render( self, mode ):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glUseProgram( self.shader )
        glActiveTexture( GL_TEXTURE0 )
        self.texture.render( mode=mode )
        glUniform1i( self.texture_location, 0 )
        glUniform3f( self.light_location, 0.408, 0.816, 0.408 )
        glUniformMatrix4fv(
            self.matrix_location, 1, GL_FALSE,
            dot( mode.matrix, mode.projection ),
        )
        glBindVertexArray( self.vao )
        try:
            self.coords.bind()
            glEnableVertexAttribArray( self.position_location )
            glVertexAttribPointer(
                self.position_location, 3, GL_FLOAT, GL_FALSE, 20, self.coords
            )
            glEnableVertexAttribArray( self.texcoord_location )
            glVertexAttribPointer(
                self.texcoord_location, 2, GL_FLOAT, GL_FALSE, 20,
                self.coords+12
            )
            self.indices.bind()
            # Can loop loading matrix and calling just this function 
            # for each sphere you want to render...
            # include both scale and position in the matrix...
            glDrawElements(
                GL_TRIANGLES, self.coordLength, GL_UNSIGNED_SHORT, self.indices
            )
        finally:
            self.indices.unbind()
            self.coords.unbind()
            glBindVertexArray( 0 )
            glUseProgram( 0 )
        

if __name__ == "__main__":
    #import cProfile
    #cProfile.run( 'TestContext.ContextMainLoop()', 'sphere.profile' )
    TestContext.ContextMainLoop()

#	sphere( pi/4 )
    