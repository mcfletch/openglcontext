#! /usr/bin/env python
import OpenGL 
OpenGL.USE_ACCELERATE = False
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGL.GL import shaders
from OpenGLContext.arrays import *
import time

class TestContext( BaseContext ):
    def OnInit( self ):
        vertex = shaders.compileShader("""#version 330 core
            uniform mat4 modelViewProjection;
            uniform float end_fog;
            uniform vec4 fog_color;
            in vec3 Vertex_position;
            in vec3 Vertex_color;
            out vec4 vertex_color;
            void main() {
                float fog; // amount of fog to apply
                float fog_coord; // distance for fog calculation...
                gl_Position = modelViewProjection * vec4(
                    Vertex_position, 1.0
                );

                fog_coord = abs(gl_Position.z);
                fog_coord = clamp( fog_coord, 0.0, end_fog);
                fog = (end_fog - fog_coord)/end_fog;
                fog = clamp( fog, 0.0, 1.0);
                vertex_color = mix(
                    fog_color, vec4( Vertex_color, 1.0 ), fog
                );
            }""",GL_VERTEX_SHADER)
        fragment = shaders.compileShader("""#version 330 core
            in vec4 vertex_color;
            out vec4 fragColor;
            void main() {
                fragColor = vertex_color;
            }""",GL_FRAGMENT_SHADER)
        self.shader = shaders.compileProgram(vertex,fragment)
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
        self.UNIFORM_LOCATIONS = {
            'modelViewProjection': glGetUniformLocation(
                self.shader, 'modelViewProjection'
            ),
            'end_fog': glGetUniformLocation( self.shader, 'end_fog' ),
            'fog_color': glGetUniformLocation( self.shader, 'fog_color' ),
        }
        self.Vertex_position_loc = glGetAttribLocation(
            self.shader, 'Vertex_position'
        )
        self.Vertex_color_loc = glGetAttribLocation(
            self.shader, 'Vertex_color'
        )
        self.vao = glGenVertexArrays( 1 )
    def OnIdle( self, event=None ):
        self.triggerRedraw(1)
    def Render( self, mode ):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glUseProgram(self.shader)
        glUniform1f( self.UNIFORM_LOCATIONS['end_fog'],15)
        glUniform4f(self.UNIFORM_LOCATIONS['fog_color'],1,1,1,1)
        angle = pi/4.0
        model = array([
            [ 3*cos(angle), 0,-3*sin(angle), 0],
            [ 0,            3, 0,            0],
            [ 3*sin(angle), 0, 3*cos(angle), 0],
            [ 0,            0, 0,            1],
        ],'f')
        glUniformMatrix4fv(
            self.UNIFORM_LOCATIONS['modelViewProjection'], 1, GL_FALSE,
            dot( dot( model, mode.matrix ), mode.projection ),
        )
        
        self.vbo[0:1] = array([0,(time.time()%1.0)*.5+.5,0,0,1,0],'f')
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
                glVertexAttribPointer(
                    self.Vertex_color_loc, 3, GL_FLOAT, GL_FALSE, 24,
                    self.vbo+12
                )
                glDrawArrays(GL_TRIANGLES, 0, 9)
            finally:
                self.vbo.unbind()
                glDisableVertexAttribArray( self.Vertex_position_loc )
                glDisableVertexAttribArray( self.Vertex_color_loc )
        finally:
            glBindVertexArray( 0 )
            glUseProgram( 0 )
        
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARN )
    TestContext.ContextMainLoop()
'''You may wish to use the keyboard "arrow" keys to walk around in the 
"foggy" world and see the effect update as your move closer to or further away from the geometry.'''
