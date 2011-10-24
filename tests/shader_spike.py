#! /usr/bin/env python
'''Shader sample-code for OpenGLContext
'''
import OpenGL 
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders
from OpenGLContext.scenegraph.shaders import (
    glUseProgram, glGetAttribLocation, 
    glVertexAttribPointer,ShaderBuffer,
)

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
        self.shader = shaders.compileProgram(
            shaders.compileShader(
                '''
                attribute vec3 position;
                attribute vec3 color;
                varying vec4 baseColor;
                void main() {
                    gl_Position = gl_ModelViewProjectionMatrix * vec4( position,1.0);
                    baseColor = vec4(color,1.0);
                }''',
                GL_VERTEX_SHADER,
            ),
            shaders.compileShader(
                '''varying vec4 baseColor;
                void main() { 
                    gl_FragColor = baseColor;
                }''',
                GL_FRAGMENT_SHADER,
            ),
        )
        self.vbo = vbo.VBO( array([ 
                [  0, 1, 0,  0,1,0 ],
                [ -1,-1, 0,  1,1,0 ],
                [  1,-1, 0,  0,1,1 ],
                
                [  2,-1, 0,  1,0,0 ],
                [  4,-1, 0,  0,1,0 ],
                [  4, 1, 0,  0,0,1 ],
                [  2,-1, 0,  1,0,0 ],
                [  4, 1, 0,  0,0,1 ],
                [  2, 1, 0,  0,1,1 ],
            ], 'f')
        )
        self.position_location = glGetAttribLocation( 
            self.shader, 'position' 
        )
        self.color_location = glGetAttribLocation( 
            self.shader, 'color' 
        )
    
    def Render( self, mode = 0):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glUseProgram(self.shader)
        try:
            self.vbo.bind()
            glVertexAttribPointer( 
                self.position_location, 3, GL_FLOAT,False, 24, self.vbo 
            )
            glEnableVertexAttribArray( self.position_location )
            self.vbo.bind()
            glVertexAttribPointer( 
                self.color_location, 3, GL_FLOAT,False, 24, self.vbo+12 
            )
            glEnableVertexAttribArray( self.color_location )
            glDrawArrays(GL_TRIANGLES, 0, 9)
            self.vbo.unbind()
        finally:
            glUseProgram( 0 )
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
