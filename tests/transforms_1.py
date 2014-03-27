#! /usr/bin/env python
'''=Understanding Transforms=

[transforms_1.py-screen-0001.png Screenshot]

In this tutorial we'll learn:

    * How OpenGL transforms work
    * How we manipulate transforms

We assume you've completed the shader tutorials so that 
you will be able to figure out how the code works...
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
                FloatUniformm4(name="color" ),
            ],
            textures = [
            ],
            shaders = [
                GLSLShader(
                    source = [ '''#version 120
                    uniform mat4 transform;
                    attribute vec3 Vertex_position;
                    varying vec4 baseColor;
                    void main() {
                        gl_Position = transform * vec4(
                            Vertex_position, 1.0
                        );
                        baseColor = gl_Position;
                    }''' ],
                    type = 'VERTEX',
                ),
                GLSLShader(
                    source = [ '''#version 120
                    uniform vec4 color;
                    varying vec4 baseColor;
                    void main() {
                        gl_FragColor = vec4((baseColor.xyz+vec3(1,1,1))/2,1);
                    }
                    '''],
                    type = 'FRAGMENT',
                ),
            ]
        )
        self.coords = ShaderBuffer( buffer = array([
            (1,1,-1),
            (-1,1,-1),
            (0,-1,-1),
            
            (0,1,0),
            (-1,-1,0),
            (1,-1,0),


        ], dtype='f'))
        self.coord_mult = array([(x,y,z,0) for (x,y,z) in self.coords.buffer],dtype='f')
        self.indices = ShaderIndexBuffer( buffer = array([0,1,2,3,4,5],dtype='I') )
        self.attributes = [
            ShaderAttribute(
                name = 'Vertex_position',
                offset = 0,
                stride = 4*3,
                buffer = self.coords,
                isCoord = True,
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
                [0,0,-.99999,0],
                [0,0,0,1],
            ],'f'),
            array([
                [.5,0,0,0],
                [0,1,0,0],
                [0,0,-.99999,0],
                [0,0,0,1],
            ],'f'),
            array([
                [1,0,0,0],
                [0,.5,0,0],
                [0,0,-.99999,0],
                [0,0,0,1],
            ],'f'),
            array([
                [1,0,0,0],
                [0,1,0,0],
                [0,0,-.99999,0],
                [1,0,0,1],
            ],'f'),
            array([
                [1,0,0,0],
                [0,1,0,0],
                [0,0,-.99999,0],
                [0,1,0,1],
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
                GL_TRIANGLES, 6,
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
