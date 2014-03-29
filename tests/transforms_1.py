#! /usr/bin/env python
'''=Understanding Transforms=

In this tutorial we'll learn:

    * How OpenGL transforms work
    * How we manipulate transforms

We'll get started by doing some basic imports to get the 
OpenGLContext context, numpy, and all the other tools 
we're going to use.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders
from OpenGLContext.scenegraph.basenodes import *
'''This utility provides transformation-matrix calculation on the CPU'''
from vrml.vrml97 import transformmatrix
'''

_The Theory_

OpenGL hardware renders a 2x2x2 cube:

 * Z goes from -1 at the far clipping plane to 1 at the near clipping plane
 * X goes from -1 at the left to 1 at the right
 * Y goes from -1 at the bottom to 1 at the top.

The OpenGL hardware will clip out geometry which does not fall within 
the 2x2x2 cube.  If you draw outside the cube, the geometry just won't
show up at all.  The hardware always draws the same cube, and nothing 
you do is going to alter that cube, all you can do is map 
your geometry into the cube properly.

_How We're Drawing_

We are going to start off with an identity matrix for our transformation.
When an identity matrix is multiplied by a coordinate the coordinate is 
unchanged. Thus we are going to be drawing in raw "device" or "display"
coordinates.

Note: OpenGL perspective/orthographic routines generally include a 
scale of -1 in the Z coordinate.
'''
identity_matrix = array([
    [1,0,0,0],
    [0,1,0,0],
    [0,0,1,0],
    [0,0,0,1],
], dtype='f')
'''
Our shader in this scene takes a single matrix uniform (our identity matrix 
to start) and multiplies it by the coordinates in our triangles. It sets the 
color of each vertex to the colours in the triangles as well. It does *not*
take into account the OpenGLContext built-in navigation, perspective matrix, 
and the like. As a result, the scene will be entirely static when displayed.
'''
SHADERS = [
    GLSLShader(
        source = [ """#version 120
        uniform mat4 transform;
        attribute vec3 Vertex_position;
        attribute vec4 Vertex_color;
        varying vec4 baseColor;
        void main() {
            baseColor = Vertex_color;
            gl_Position = transform * vec4(
                Vertex_position, 1.0
            );
        }""" ],
        type = 'VERTEX',
    ),
    GLSLShader(
        source = [ """#version 120
        uniform vec4 color;
        varying vec4 baseColor;
        void main() {
            gl_FragColor = baseColor;
        }
        """],
        type = 'FRAGMENT',
    ),
]

'''
[transforms_1.py-screen-0002.png Screenshot]

_What We're Drawing_

We will draw four triangles.  The first is a cyan triangle which will 
*not* appear in the rendering. It is being drawn at Z == -1.05, so it 
is behind the clipping region.
'''
cyan_triangle = [
    (0,2,-1.05,   0,1,1,.5),
    (0,-2,-1.05, 0,1,1,.5),
    (2,-2,-1.05,  0,1,1,.5),
]
'''
The small blue triangle will be drawn at Z == -.5
'''
blue_triangle = [
    (1,1,.5,  1,0,0,.5),
    (-1,1,.5, 1,0,0,.5),
    (0,-1,.5, 1,0,0,.5),
]
'''The green triangle will be drawn at Z == 0.'''
green_triangle = [
    (0,1,0,   0,1,0,.5),
    (-1,-1,0, 0,1,0,.5),
    (1,-1,0,  0,1,0,.5),
]
'''The red triangle will be drawn at Z == .5'''
red_triangle = [
    (0,1,-.5,   0,0,1,.5),
    (0,-1,-.5, 0,0,1,.5),
    (1,-1,-.5,  0,0,1,.5),
]
'''
_Scaling the Scene_

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




class TestContext( BaseContext ):
    """Creates a simple vertex shader..."""
    @property
    def perspective( self ):
        return self.perspective_matrices[self.perspective_index]
    
    def OnInit( self ):
        self.glslObject = GLSLObject(
            uniforms = [ FloatUniformm4(name="transform" ) ],
            shaders = SHADERS,
        )
        self.coords = ShaderBuffer( 
            buffer = array( 
                blue_triangle + green_triangle + red_triangle + cyan_triangle,
                dtype='f'
            )
        )
        # An array of *just* coordinates we'll use to display the transformed 
        # coordinates (we don't use these for rendering)
        self.coord_mult = array([
            (x,y,z,1) 
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
        
        
        self.perspective_index = 0
        aspect = self.getViewPort()
        if aspect[1]:
            aspect = aspect[0]/aspect[1]
        else:
            aspect = 1
        self.perspective_matrices = [
            identity_matrix,
            array([
                [.5,0,0,0],
                [0,1,0,0],
                [0,0,1,0],
                [0,0,0,1],
            ],'f'),
            array([
                [1,0,0,0],
                [0,.5,0,0],
                [0,0,1,0],
                [0,0,0,1],
            ],'f'),
            array([
                [1,0,0,0],
                [0,1,0,0],
                [0,0,1,0],
                [.5,0,0,1],
            ],'f'),
            array([
                [1,0,0,0],
                [0,1,0,0],
                [0,0,1,0],
                [0,.5,0,1],
            ],'f'),
        ] + [
            dot(array([
                [1,0,0,0],
                [0,1,0,0],
                [0,0,-1,0],
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
        final_matrix = self.perspective
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
