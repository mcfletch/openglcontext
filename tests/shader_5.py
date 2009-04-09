#! /usr/bin/env python
'''Shader sample-code for OpenGLContext
'''
import OpenGL 
OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGLContext.scenegraph.shaders import *

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
		self.shader = compileProgram(
			'''
			attribute vec3 position;
			attribute vec3 color;
			varying vec4 baseColor;
			void main() {
				gl_Position = gl_ModelViewProjectionMatrix * vec4( position,1.0);
				baseColor = vec4(color,1.0);
			}''',
			'''
			varying vec4 baseColor;
			void main() {
				gl_FragColor = baseColor;
			}''',
		)
		self.buffer = ShaderBuffer( buffer = array( [
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
		print self.buffer.buffer
		self.position_location = glGetAttribLocation( 
			self.shader, 'position' 
		)
		self.color_location = glGetAttribLocation( 
			self.shader, 'color' 
		)
	
	def Render( self, mode = 0):
		"""Render the geometry for the scene."""
		BaseContext.Render( self, mode )
		vbo = self.buffer.vbo( mode )
		glUseProgram(self.shader)
		try:
			vbo.bind()
			try:
				glVertexAttribPointer( 
					self.position_location, 3, GL_FLOAT,False, 24, vbo 
				)
				glVertexAttribPointer( 
					self.color_location, 3, GL_FLOAT,False, 24, vbo+12 
				)
				glEnableVertexAttribArray( self.position_location )
				glEnableVertexAttribArray( self.color_location )
				glDrawArrays(GL_TRIANGLES, 0, 9)
			finally:
				vbo.unbind( )
		finally:
			glUseProgram( 0 )
		

if __name__ == "__main__":
	MainFunction ( TestContext)

