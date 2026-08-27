#! /usr/bin/env python
'''Shader sample-code for OpenGLContext
'''
#import OpenGL 
#OpenGL.FULL_LOGGING = True
#OpenGL.USE_ACCELERATOR = False
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GL import shaders
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
import ctypes

class TestContext( BaseContext ):
    """The same two attributes as shader_2, with the colour offset given
    as a raw pointer rather than as an offset into the VBO wrapper.
    """
    
    def OnInit( self ):
        self.shader = shaders.compileProgram(
            shaders.compileShader(
                '''#version 330 core
                uniform mat4 modelViewProjection;
                in vec3 Vertex_position;
                in vec3 Vertex_color;
                out vec4 vertex_color;
                void main() {
                    gl_Position = modelViewProjection * vec4(
                        Vertex_position, 1.0
                    );
                    vertex_color = vec4( Vertex_color, 1.0 );
                }''',
                GL_VERTEX_SHADER,
            ),
            shaders.compileShader(
                '''#version 330 core
                in vec4 vertex_color;
                out vec4 fragColor;
                void main() {
                    fragColor = vertex_color;
                }''',
                GL_FRAGMENT_SHADER,
            ),
        )
        self.modelViewProjection_loc = glGetUniformLocation(
            self.shader, 'modelViewProjection'
        )
        self.Vertex_position_loc = glGetAttribLocation(
            self.shader, 'Vertex_position'
        )
        self.Vertex_color_loc = glGetAttribLocation(
            self.shader, 'Vertex_color'
        )
        self.vao = glGenVertexArrays( 1 )
        self.vbo = vbo.VBO(
            array( [
                [  0, 1, 0,  0,1,0 ],
                [ -1,-1, 0,  1,1,0 ],
                [  1,-1, 0,  0,1,1 ],
                
                [  2,-1, 0,  1,0,0 ],
                [  4,-1, 0,  0,1,0 ],
                [  4, 1, 0,  0,0,1 ],
                [  2,-1, 0,  1,0,0 ],
                [  4, 1, 0,  0,0,1 ],
                [  2, 1, 0,  0,1,1 ],
            ],'f')
        )
    
    def Render( self, mode ):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        shaders.glUseProgram(self.shader)
        glUniformMatrix4fv(
            self.modelViewProjection_loc, 1, GL_FALSE,
            dot( mode.matrix, mode.projection ),
        )
        glBindVertexArray( self.vao )
        try:
            self.vbo.bind()
            try:
                glEnableVertexAttribArray( self.Vertex_position_loc )
                glEnableVertexAttribArray( self.Vertex_color_loc )
                glVertexAttribPointer(
                    self.Vertex_position_loc, 3, GL_FLOAT, GL_FALSE, 24,
                    self.vbo
                )
                # The offset given as a raw pointer, rather than as
                # self.vbo+12; both name the same place in the buffer.
                glVertexAttribPointer(
                    self.Vertex_color_loc, 3, GL_FLOAT, GL_FALSE, 24,
                    ctypes.c_void_p(12)
                )
                glDrawArrays(GL_TRIANGLES, 0, 9)
            finally:
                self.vbo.unbind()
        finally:
            glBindVertexArray( 0 )
            shaders.glUseProgram( 0 )
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
