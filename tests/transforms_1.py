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
                    void main() {
                        gl_Position = transform * vec4(
                            Vertex_position, 1.0
                        );
                    }''' ],
                    type = 'VERTEX',
                ),
                GLSLShader(
                    source = [ '''#version 120
                    void main() {
                        gl_FragColor = vec4( 1,0,0,1 );
                    }
                    '''],
                    type = 'FRAGMENT',
                ),
            ]
        )
        self.coords = ShaderBuffer( buffer = array([
            (0,1,0),
            (-1,-1,0),
            (1,-1,0),
        ], dtype='f'))
        self.coord_mult = array([(x,y,z,0) for (x,y,z) in self.coords.buffer],dtype='f')
        self.indices = ShaderIndexBuffer( buffer = array([0,1,2],dtype='I') )
        self.attributes = [
            ShaderAttribute(
                name = 'Vertex_position',
                offset = 0,
                stride = 4*3,
                buffer = self.coords,
                isCoord = True,
            ),
        ]
        self.matrix = identity(4,dtype='f')
        self.perspective = identity( 4, dtype='f')
        self.showing_perspective = False
        self.addEventHandler( "keypress", name="p", function = self.OnPerspective)
    def Render( self, mode):
        """Render the geometry for the scene."""
        if not mode.visible:
            return
        final_matrix = dot( self.perspective, self.matrix )
        print('final_matrix:\n%s'%(final_matrix))
        print('transformed:\n%s'%( dot( self.coord_mult, final_matrix )))
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
                GL_TRIANGLES, 3,
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
        if self.showing_perspective:
            self.perspective = identity(4,dtype='f')
        else:
            self.perspective = transformmatrix.orthoMatrix(
                left=-2,
                right=2,
                bottom=-2,
                top=-2,
                zNear=-2,
                zFar=2
            )
        self.showing_perspective = not(self.showing_perspective)
        self.triggerRedraw()
        
        
if __name__ == "__main__":
    TestContext.ContextMainLoop()
