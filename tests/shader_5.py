#! /usr/bin/env python
'''=Diffuse (and Ambient) Lighting=

[shader_5.py-screen-0001.png Screenshot]

This tutorial builds on earlier tutorials by adding:

	* ambient lighting 
	* diffuse lighting 
	* normals, lights, GLSL structures

Lighting is one of the most complex aspects of the rendering 
process.  There are a multitude of ways of simulating how 
light interacts with surfaces, from the traditional OpenGL 
phong-like lighting model, through complex sub-surface scattering
mechanisms required to create "realistic" skin.  This tutorial 
is merely going to introduce the basics of lighting calculations.
'''
import OpenGL 
OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL.shaders import *
'''This is our only new import, it's a utility Timer object 
from OpenGLContext which will generate events with "fraction()"
values that can be used for animations.'''
from OpenGLContext.events.timer import Timer

class TestContext( BaseContext ):
	"""Demonstrates use of attribute types in GLSL
	"""
	def OnInit( self ):
		"""Initialize the context"""
		vertex = compileShader("""
		
		uniform vec4 Light_ambient;
		uniform vec4 Light_diffuse;
		uniform vec3 Light_location;
		
		uniform vec4 Material_ambient;
		uniform vec4 Material_diffuse;
		
		attribute vec3 Vertex_position;
		attribute vec3 Vertex_normal;
		
		varying vec4 baseColor;
		vec2 dLight( 
			in vec3 light_pos, // light position
			in vec3 frag_normal // geometry normal
		) {
			// returns vec2( ambientMult, diffuseMult )
			float n_dot_pos = max( 0.0, dot( 
				frag_normal, normalize(light_pos)
			));
			return vec2( 1.0, n_dot_pos );
		}		
		void main() {
			gl_Position = gl_ModelViewProjectionMatrix * vec4( 
				Vertex_position, 1.0
			);
			vec3 EC_Light_location = gl_NormalMatrix * Light_location;
			vec2 weights = dLight(
				normalize(EC_Light_location),
				normalize(gl_NormalMatrix * Vertex_normal)
			);
			
			vec4 ambient = vec4( .1, .1, .1, .1 );
			vec4 diffuse = vec4( 0.0, 1.0, 0.0, 1.0 );
			
			baseColor = clamp( (
				Light_ambient * Material_ambient * weights.x
			)+ (
				Light_diffuse * Material_diffuse * weights.y 
			), 0.0, 1.0);
		}""", GL_VERTEX_SHADER)
		fragment = compileShader("""
		varying vec4 baseColor;
		void main() {
			gl_FragColor = baseColor;
		}
		""", GL_FRAGMENT_SHADER)
		
		self.shader = compileProgram(vertex,fragment)
		'''We're going to create slightly less "flat" geometry for this 
		lesson, we'll create a set of 4 faces in a "bow window" 
		arrangement that makes it easy to see the effect of the direct 
		lighting.'''
		self.vbo = vbo.VBO(
			array( [
				[ -1, 0, 0, -1,0,1],
				[  0, 0, 1, -1,0,2],
				[  0, 1, 1, -1,0,2],
				[ -1, 0, 0, -1,0,1],
				[  0, 1, 1, -1,0,2],
				[ -1, 1, 0, -1,0,1],
				
				[  0, 0, 1, -1,0,2],
				[  1, 0, 1, 1,0,2],
				[  1, 1, 1, 1,0,2],
				[  0, 0, 1, -1,0,2],
				[  1, 1, 1, 1,0,2],
				[  0, 1, 1, -1,0,2],
				
				[  1, 0, 1, 1,0,2],
				[  2, 0, 0, 1,0,1],
				[  2, 1, 0, 1,0,1],
				[  1, 0, 1, 1,0,2],
				[  2, 1, 0, 1,0,1],
				[  1, 1, 1, 1,0,2],
			],'f')
		)
		'''As with uniforms, we must use opaque "location" values 
		to refer to our attributes when calling into the GL.'''
		self.position_location = glGetAttribLocation( 
			self.shader, 'position' 
		)
		self.normal_location = glGetAttribLocation(
			self.shader, 'norm',
		)
		self.color_location = glGetUniformLocation(
			self.shader, 'color',
		)
		
		for uniform in (
			'Light_ambient','Light_diffuse','Light_location',
			'Material_ambient','Material_diffuse',
		):
			location = glGetUniformLocation( self.shader, uniform )
			if location in (None,-1):
				print 'Warning, no uniform: %s'%( uniform )
			setattr( self, uniform+ '_loc', location )
			
		for attribute in (
			'Vertex_position','Vertex_normal',
		):
			location = glGetAttribLocation( self.shader, attribute )
			if location in (None,-1):
				print 'Warning, no attribute: %s'%( uniform )
			setattr( self, attribute+ '_loc', location )
		
	
	def Render( self, mode = None):
		"""Render the geometry for the scene."""
		BaseContext.Render( self, mode )
		glUseProgram(self.shader)
		'''We pass in the current (for this frame) value of our 
		animation fraction.  The timer will generate events to update
		this value during idle time.'''
		try:
			self.vbo.bind()
			try:
				glUniform4f( self.Light_ambient_loc, .2,.2,.2, 1.0 )
				glUniform4f( self.Light_diffuse_loc, 1,1,1,1 )
				glUniform3f( self.Light_location_loc, 2,2,10 )
				glUniform4f( self.Material_ambient_loc, .2,.2,.2, 1.0 )
				glUniform4f( self.Material_diffuse_loc, 1,1,1, 1 )
				
				
				glEnableVertexAttribArray( self.Vertex_position_loc )
				glEnableVertexAttribArray( self.Vertex_normal_loc )
				stride = 6*4
				glVertexAttribPointer( 
					self.Vertex_position_loc, 
					3, GL_FLOAT,False, stride, self.vbo 
				)
				glVertexAttribPointer( 
					self.Vertex_normal_loc, 
					3, GL_FLOAT,False, stride, self.vbo+12
				)
				glDrawArrays(GL_TRIANGLES, 0, 18)
			finally:
				self.vbo.unbind()
				'''As with the legacy pointer operations, we want to 
				clean up our array enabling so that any later calls 
				will not cause seg-faults when they try to read records
				from these arrays (potentially beyond the end of the
				arrays).'''
				glDisableVertexAttribArray( self.Vertex_position_loc )
				glDisableVertexAttribArray( self.Vertex_normal_loc )
		finally:
			glUseProgram( 0 )

if __name__ == "__main__":
	MainFunction ( TestContext)
