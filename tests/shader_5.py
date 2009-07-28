#! /usr/bin/env python
'''=Diffuse (and Ambient) Lighting=

[shader_5.py-screen-0001.png Screenshot]

This tutorial builds on earlier tutorials by adding:

	* ambient lighting 
	* diffuse lighting 
	* normals, lights, GLSL structures

Lighting is one of the most complex aspects of the rendering 
process.  No-one has yet come up with a "perfect" simulation 
of rendering for use in real-time graphics (even non-real-time 
graphics haven't really solved the problem for every material).

So every OpenGL renderer is an approximation of what a particular 
material should look like under some approximation of a particular 
lighting environment.  Traditional (legacy) OpenGL had a particular 
lighting model which often "worked" for simple visualizations of 
geometry.  This tutorial is going to show you how to start creating 
a similar lighting effect.

== Ambient Lighting ==

Ambient lighting is used to simulate the "radiant" effect in lighting,
that is, the effect of light which is "bouncing around" the environment 
which otherwise isn't accounted for by your lighting model.

In Legacy OpenGL, ambient light was handled as a setting declaring
each surface's ambient reflectance (a colour), with a set of two 
"light sources" which would be reflected.  The first light source was
the simplest, this was a simple global ambient value, which was applied
to all surfaces.  The ambient contribution for each material here is
simply:

	Global_ambient * Material_ambient 

which provides a "base" colour for each material.  You can think of 
this as the not-quite-black colour of objects with no direct lights 
hitting them and no local objects reflecting light onto them.  The
material's ambient value can be thought of as "how much of the ambient
light does the material re-emit" (as opposed to absorbing).

Note, that all of the ambient values here are 4-component colours.

== Diffuse Lighting ==

Diffuse lighting is used to simulate re-emission from a surface where 
the re-emittance isn't "ordered" (that is, is diffused).  A "non-shiny"
surface which re-emits everything that hits it (think snow, for instance)
would have a very high "diffuse" lighting value.  A diffuse surface 
emits light in *all* directions whenever hit by a light, but the amount 
of light it emits is controlled by the angle at which the light hits 
the surface.


'''
#import OpenGL 
#OpenGL.FULL_LOGGING = True
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
		dLight = """
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
		"""
		
		vertex = compileShader( dLight + 
		"""
		uniform vec4 Global_ambient;
		
		uniform vec4 Light_ambient;
		uniform vec4 Light_diffuse;
		uniform vec3 Light_location;
		
		uniform vec4 Material_ambient;
		uniform vec4 Material_diffuse;
		
		attribute vec3 Vertex_position;
		attribute vec3 Vertex_normal;
		
		varying vec4 baseColor;
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
			
			baseColor = clamp( 
			(
				// global component 
				(Global_ambient * Material_ambient)
				// material's interaction with light's contribution 
				// to the ambient lighting...
				+ (Light_ambient * Material_ambient * weights.x)
				// material's interaction with the direct light from 
				// the light.
				+ (Light_diffuse * Material_diffuse * weights.y)
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
		'''Since we have so many more uniforms and attributes, we'll 
		use a bit of iteration to set up the values for ourselves.'''
		for uniform in (
			'Global_ambient',
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
				'''We add a strong red tinge so you can see the 
				global ambient light's contribution.'''
				glUniform4f( self.Global_ambient_loc, .3,.05,.05,.1 )
				
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
