#! /usr/bin/env python
'''Shader sample-code for OpenGLContext
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGLContext.scenegraph.shaders import *
from OpenGL.GLUT import glutSolidTeapot

class TestContext( BaseContext ):
	"""This shader adds a simple linear fog to the shader
	
	Shows use of uniforms, and a few simple calculations 
	within the vertex shader...
	"""
	UNIFORM_VALUES = (
		(glUniform1f,'end_fog',(12,)),
		(glUniform4f,'fog_color',(0,0,0,1)),
	)
	def OnInit( self ):
		self.shader = compileProgram(
			'''
			uniform float end_fog;
			uniform vec4 fog_color;
			void main() {
				float fog; // amount of fog to apply
				float fog_coord; // distance for fog calculation...
				gl_Position = ftransform();
				//gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
				// ecPosition is the eye-coordinate position...
				
				fog_coord = abs(gl_Position.z);
				fog_coord = clamp( fog_coord, 0.0, end_fog);
				fog = (end_fog - fog_coord)/end_fog;
				fog = clamp( fog, 0.0, 1.0);
				gl_FrontColor = mix(fog_color, gl_Color, fog);
			}''',
			'''void main() {
				gl_FragColor = gl_Color;
			}''',
		)
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
		self.UNIFORM_LOCATIONS = {}
		for func,var,values in self.UNIFORM_VALUES:
			loc = glGetUniformLocation( self.shader, var )
			self.UNIFORM_LOCATIONS[var] = loc
	
	def Render( self, mode = 0):
		"""Render the geometry for the scene."""
		BaseContext.Render( self, mode )
		glUseProgram(self.shader)
		for func,var,values in self.UNIFORM_VALUES:
			loc = self.UNIFORM_LOCATIONS[var]
			func( loc, *values )
		glRotate( 45, 0,1,0 )
		glScale( 3,3,3 )
		try:
			self.vbo.bind()
			try:
				glEnableClientState(GL_VERTEX_ARRAY);
				glEnableClientState(GL_COLOR_ARRAY);
				glVertexPointer(3, GL_FLOAT, 24, self.vbo )
				glColorPointer(3, GL_FLOAT, 24, self.vbo+12 )
				glDrawArrays(GL_TRIANGLES, 0, 9)
			finally:
				self.vbo.unbind()
		finally:
			glUseProgram( 0 )
		

if __name__ == "__main__":
	MainFunction ( TestContext)

