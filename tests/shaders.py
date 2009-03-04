#! /usr/bin/env python
'''Tests rendering using the ARB shader objects extension...
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GL.ARB.shader_objects import *
from OpenGL.GL.ARB.fragment_shader import *
from OpenGL.GL.ARB.vertex_shader import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from OpenGLContext.arrays import array
import time, sys,logging
log = logging.getLogger( 'shaderobjects' )
from OpenGL.extensions import alternate
glCreateShader = alternate( 'glCreateShader', glCreateShader, glCreateShaderObjectARB )
glShaderSource = alternate( 'glShaderSource', glShaderSource, glShaderSourceARB)
glCompileShader = alternate( 'glCompileShader', glCompileShader, glCompileShaderARB)
glCreateProgram = alternate( 'glCreateProgram', glCreateProgram, glCreateProgramObjectARB)
glAttachShader = alternate( 'glAttachShader', glAttachShader,glAttachObjectARB )
glValidateProgram = alternate( 'glValidateProgram',glValidateProgram,glValidateProgramARB )
glLinkProgram = alternate( 'glLinkProgram',glLinkProgram,glLinkProgramARB )
glDeleteShader = alternate( 'glDeleteShader', glDeleteShader,glDeleteObjectARB )
glUseProgram = alternate('glUseProgram',glUseProgram,glUseProgramObjectARB )

glGetProgramInfoLog = alternate( glGetProgramInfoLog, glGetInfoLogARB )
glGetUniformLocation = alternate( glGetUniformLocation, glGetUniformLocationARB )
glUniform3fv = alternate( glUniform3fv, glUniform3fvARB )


def compileShader( source, shaderType ):
	"""Compile shader source of given type"""
	shader = glCreateShader(shaderType)
	glShaderSource( shader, source )
	glCompileShader( shader )
	return shader


def compileProgram(vertexSource=None, fragmentSource=None):
	program = glCreateProgram()

	if vertexSource:
		vertexShader = compileShader(
			vertexSource, GL_VERTEX_SHADER_ARB
		)
		glAttachShader(program, vertexShader)
	if fragmentSource:
		fragmentShader = compileShader(
			fragmentSource, GL_FRAGMENT_SHADER_ARB
		)
		glAttachShader(program, fragmentShader)

	glValidateProgram( program )
	warnings = glGetProgramInfoLog( program )
	if warnings:
		log.warn( 'Program compilation log: %s', warnings )
	glLinkProgram(program)

	if vertexShader:
		glDeleteShader(vertexShader)
	if fragmentShader:
		glDeleteShader(fragmentShader)

	return program


class TestContext( BaseContext ):
	rotation = 0.00
	light_location = (0,10,0)
	def Render( self, mode = 0):
		BaseContext.Render( self, mode )
		glRotate( self.rotation, 0,1,0 )
		self.rotation += .05
		glUseProgram(self.program)
		glUniform3fv( self.light_uniform_loc, 1, self.light_location )
		glutSolidSphere(1.0,32,32)
		glTranslate( 1,0,2 )
		glutSolidCube( 1.0 )
	def OnInit( self ):
		"""Scene set up and initial processing"""
		self.program = compileProgram(
[
	'''
	varying vec3 normal;
	void main() {
		normal = gl_NormalMatrix * gl_Normal;
		gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
	}
	''',
], 
[
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
]
)
		self.light_uniform_loc = glGetUniformLocation( self.program, 'light_location' )


if __name__ == "__main__":
	MainFunction ( TestContext)

