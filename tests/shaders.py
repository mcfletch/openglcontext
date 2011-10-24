#! /usr/bin/env python
'''Tests rendering using the ARB shader objects extension...
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GL import shaders
from OpenGL.GL.ARB.shader_objects import *
from OpenGL.GL.ARB.fragment_shader import *
from OpenGL.GL.ARB.vertex_shader import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from OpenGLContext.arrays import array
from OpenGLContext.events.timer import Timer
import time, sys,logging,math
log = logging.getLogger( 'shaderobjects' )

class TestContext( BaseContext ):
    rotation = 0.00
    rotation_2 = 0.00
    light_location = (0,10,5)
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glRotate( self.rotation, 0,1,0 )
        glRotate( self.rotation_2, 1,0,1 )
        glUseProgram(self.program)
        glUniform3fv( self.light_uniform_loc, 1, self.light_location )
        glutSolidSphere(1.0,32,32)
        glTranslate( 1,0,2 )
        glutSolidCube( 1.0 )
        glTranslate( 2,0,0 )
        glFrontFace(GL_CW)
        try:
            glutSolidTeapot( 1.0)
        finally:
            glFrontFace(GL_CCW)
    def OnInit( self ):
        """Scene set up and initial processing"""
        self.program = shaders.compileProgram(
            shaders.compileShader(
                '''
                varying vec3 normal;
                void main() {
                    normal = gl_NormalMatrix * gl_Normal;
                    gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
                }
                ''',
                GL_VERTEX_SHADER,
            ),
            shaders.compileShader(
                '''
                uniform vec3 light_location;
                varying vec3 normal;
                void main() {
                    float intensity;
                    vec4 color;
                    vec3 n = normalize(normal);
                    vec3 l = normalize(light_location).xyz;
                
                    // quantize to 5 steps (0, .25, .5, .75 and 1)
                    intensity = (floor(dot(l, n) * 4.0) + 1.0)/4.0;
                    color = vec4(intensity*1.0, intensity*0.5, intensity*0.5,
                        intensity*1.0);
                
                    gl_FragColor = color;
                }
                ''',
                GL_FRAGMENT_SHADER,
            ),
        )
        self.light_uniform_loc = glGetUniformLocation( self.program, 'light_location' )
        self.time = Timer( duration = 2.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
    def OnTimerFraction( self, event ):
        self.rotation = event.fraction() * 360
        self.rotation_2 = -event.fraction() * 360
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
