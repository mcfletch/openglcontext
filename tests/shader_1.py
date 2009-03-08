#! /usr/bin/env python
'''Draw simplest possible shader-based geometry
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGLContext.scenegraph.shaders import compileProgram, glUseProgram

class TestContext( BaseContext ):
	"""Creates a simple vertex shader..."""
	
	def OnInit( self ):
		self.shader = compileProgram(
			'''
			void main() {
				gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
				gl_FrontColor = vec4( 0.0, gl_Vertex.y, 0.0, 1.0 );
			}
			''',
			'''
			void main() {
				gl_FragColor = vec4( 1.0-gl_Color.g, gl_Color.g, gl_Color.b, 1.0 );
			}
			''',
		)
		self.vbo = vbo.VBO(
			array( [
				[  0, 1, 0 ],
				[ -1,-1, 0 ],
				[  1,-1, 0 ],
				
				[  2,-1, 0 ],
				[  4,-1, 0 ],
				[  4, 1, 0 ],
				[  2,-1, 0 ],
				[  4, 1, 0 ],
				[  2, 1, 0 ],
			],'f')
		)
	
	def Render( self, mode = 0):
		"""Render the geometry for the scene."""
		BaseContext.Render( self, mode )
		
		glUseProgram(self.shader)
		try:
			self.vbo.bind()
			try:
				glEnableClientState(GL_VERTEX_ARRAY);
				glVertexPointerf( self.vbo )
				glDrawArrays(GL_TRIANGLES, 0, 9)
			finally:
				self.vbo.unbind()
		finally:
			glUseProgram( 0 )
		

if __name__ == "__main__":
	MainFunction ( TestContext)

