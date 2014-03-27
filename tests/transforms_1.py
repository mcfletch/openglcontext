#! /usr/bin/env python
'''=Understanding Transforms=

[transforms_1.py-screen-0001.png Screenshot]

In this tutorial we'll learn:

    * How OpenGL transforms work
    * How we manipulate transforms

OpenGL hardware renders a 2x2x2 cube where z starts 
at -1 at the near clipping plane and goes to 1 at the 
far clipping plane. If you use an identity matrix for 
your model-view matrix then you are drawing into that 
coordinate space directly.

We are going to draw 4 triangles in our identity coordinate 
space (and all of our coordinate spaces). The cyan triangle 
is drawn at a z coordinate of -1.05, so will not show up 
as it is outside of the clipping -1 clipping plane.

The red triangle is at -.5, the green at 0 and the blue at .5,
so when rendered with the identity transform, we see the red 
triangle in front of the green and the blue is totally obscured
by the green.

Since OpenGL is traditionally a right-hand-rule API, our first 
transformation will be to scale the coordinate system by (1,1,-1)
so that our geometry is interpreted as though it were in an RHR
system.

Let's apply a few more scales to the matrix to get a feel for 
how they work. The diagonal values in the matrix map to individual
components, so it is pretty easy to calculate scale matrices.

Now let's apply a few translations (moves), we add the values 
to the bottom row of the matrix to get the values added to the 
coordinates.

Now let's see what happens to the matrix when we apply a perspective 
transformation.  A perspective transformation basically takes a 
truncated pyramid and maps it into the 2x2x2 cube. The front clipping 
plane (the small surface where the pyramid is truncated) maps to the 
2x2x2 cube's front-face, and the back clipping plane (the much larger 
base) maps to the 2x2x2 cube's back-face.  Coordinates closer to the 
back clipping plane are thus compressed (seem smaller), while those at 
the front clipping plane are close to uncompressed.

The perspective matrix calculation here is doing the calculations 
required to give you a particular field of view, near and far clipping 
plane. It also includes the z-axis reflection.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders
from OpenGLContext.scenegraph.basenodes import *
'''These utilities provide transformation-matrix calculation on the CPU'''
from vrml.vrml97 import transformmatrix

class TestContext( BaseContext ):
    """Creates a simple vertex shader..."""
    @property
    def perspective( self ):
        return self.perspective_matrices[self.perspective_index]
    
    def OnInit( self ):
        self.glslObject = GLSLObject(
            uniforms = [
                FloatUniformm4(name="transform" ),
            ],
            textures = [
            ],
            shaders = [
                GLSLShader(
                    source = [ '''#version 120
                    uniform mat4 transform;
                    attribute vec3 Vertex_position;
                    attribute vec4 Vertex_color;
                    varying vec4 baseColor;
                    void main() {
                        baseColor = Vertex_color;
                        gl_Position = transform * vec4(
                            Vertex_position, 1.0
                        );
                    }''' ],
                    type = 'VERTEX',
                ),
                GLSLShader(
                    source = [ '''#version 120
                    uniform vec4 color;
                    varying vec4 baseColor;
                    void main() {
                        gl_FragColor = baseColor;
                    }
                    '''],
                    type = 'FRAGMENT',
                ),
            ]
        )
        self.coords = ShaderBuffer( buffer = array([
            (0,2,-1.05,   0,1,1,.5),
            (0,-2,-1.05, 0,1,1,.5),
            (2,-2,-1.05,  0,1,1,.5),
            
            (1,1,-.5,  1,0,0,.5),
            (-1,1,-.5, 1,0,0,.5),
            (0,-1,-.5, 1,0,0,.5),
            
            (0,1,0,   0,1,0,.5),
            (-1,-1,0, 0,1,0,.5),
            (1,-1,0,  0,1,0,.5),
            
            (0,1,.5,   0,0,1,.5),
            (0,-1,.5, 0,0,1,.5),
            (1,-1,.5,  0,0,1,.5),
        ], dtype='f'))
        self.coord_mult = array([
            (x,y,z,0) 
            for (x,y,z) in self.coords.buffer[:,:3]
        ],dtype='f')
        self.indices = ShaderIndexBuffer( buffer = array(range(len(self.coords.buffer)),dtype='I') )
        self.attributes = [
            ShaderAttribute(
                name = 'Vertex_position',
                offset = 0,
                stride = 4*len(self.coords.buffer[0]),
                buffer = self.coords,
                isCoord = True,
            ),
            ShaderAttribute(
                name = 'Vertex_color',
                offset = 3*4,
                stride = 4*len(self.coords.buffer[0]),
                buffer = self.coords,
                isCoord = False,
            ),
        ]
        self.addEventHandler( "keypress", name="p", function = self.OnPerspective)
        
        self.matrix = identity(4,dtype='f')
        
        self.perspective_index = 0
        aspect = self.getViewPort()
        if aspect[1]:
            aspect = aspect[0]/aspect[1]
        else:
            aspect = 1
        self.perspective_matrices = [
            self.matrix, # identity 
            array([ # identity with z-positive out the screen
                [1,0,0,0],
                [0,1,0,0],
                [0,0,-1,0],
                [0,0,0,1],
            ],'f'),
            array([
                [.5,0,0,0],
                [0,1,0,0],
                [0,0,-1,0],
                [0,0,0,1],
            ],'f'),
            array([
                [1,0,0,0],
                [0,.5,0,0],
                [0,0,-1,0],
                [0,0,0,1],
            ],'f'),
            array([
                [1,0,0,0],
                [0,1,0,0],
                [0,0,-1,0],
                [.5,0,0,1],
            ],'f'),
            array([
                [1,0,0,0],
                [0,1,0,0],
                [0,0,-1,0],
                [0,.5,0,1],
            ],'f'),
        ] + [
            dot(array([
                [1,0,0,0],
                [0,1,0,0],
                [0,0,1,0],
                [0,0,-1,1],
            ],'f'),transformmatrix.perspectiveMatrix( 
                fov*3.14159,
                aspect,
                .01,
                2.01,
                inverse=False,
            ))
            for fov in [.5,.6,.7,.8,.9,.95] # we don't go to 1 because then far would clip the geometry
        ]
        
    def Render( self, mode):
        """Render the geometry for the scene."""
        if not mode.visible:
            return
        final_matrix = dot( self.matrix, self.perspective )
        print('final_matrix:\n%s'%(final_matrix))
        print('transformed vertices:\n%s'%( dot( self.coord_mult, final_matrix )))
        self.glslObject.getVariable( 'transform' ).value = final_matrix
        token = self.glslObject.render( mode )
        tokens = []
        vbo = self.indices.bind(mode)
        try:
            for attribute in self.attributes:
                token = attribute.render( self.glslObject, mode )
                if token:
                    tokens.append( (attribute, token) )
            glDrawElements(
                GL_TRIANGLES, len(self.coords.buffer),
                GL_UNSIGNED_INT, vbo
            )
            
        finally:
            for attribute,token in tokens:
                attribute.renderPost( self.glslObject, mode, token )
            self.glslObject.renderPost( token, mode )
            '''The index-array VBO also needs to be unbound.'''
            vbo.unbind()
    def OnPerspective( self, event ):
        """Request to toggle matrix perspective"""
        self.perspective_index += 1
        self.perspective_index = self.perspective_index%len(self.perspective_matrices)
        self.triggerRedraw()
        
if __name__ == "__main__":
    TestContext.ContextMainLoop()
