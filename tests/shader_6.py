#! /usr/bin/env python
'''=Specular Highlights, Directional Lighting=

[shader_6.py-screen-0001.png Screenshot]

This tutorial builds on earlier tutorials by adding:

	* specular lighting (Phong Lighting)
	* specular lighting (Blinn-Phong Lighting)
	* per-fragment lighting

This tutorial completes the 
[http://en.wikipedia.org/wiki/Phong_shading Phong Shading],
rendering code that we started in the last tutorial by adding 
"specular" highlights to the material.  Specular highlights are 
basically "shininess", that is, the tendancy of a material to 
re-emit light *in a particular direction* based on the angle of 
incidence of the light ray.

Since the changes from the last tutorial are quite small, this 
will be a fairly short tutorial.
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL.shaders import *
from OpenGLContext.events.timer import Timer

class TestContext( BaseContext ):
	"""Demonstrates use of attribute types in GLSL
	"""
	def OnInit( self ):
		"""Initialize the context"""
		'''== Phong and Blinn Reflectance ==

		A shiny surface will tend to have a "bright spot" at the point 
		on the surface where the angle of incidence for the reflected
		light ray and the viewer's ray are (close to) equal.  
		A perfect mirror would have the brights spot solely when the 
		two vectors are exactly equal, while a perfect Lambertian
		surface would have the "bright spot" spread across the entire
		surface.
		
		The Phong rendering process models this as a setting, traditionally
		called material "shininess" in Legacy OpenGL.  This setting acts 
		as a power which raises the cosine (dot product) of the 
		angle between the reflected ray and the eye.  The calculation of 
		the cosine (dot product) of the two angles requires that we do 
		a dot product of the two angles once for each vertex/fragment 
		for which we wish to calculate the specular reflectance, we also 
		have to find the angle of reflectance before we can do the 
		calculation:'''
		"""
			L_dir = (V_pos-L_pos)
			R = 2N*(dot( N, L_dir))-L_dir
			// Note: in eye-coordinate system, Eye_pos == (0,0,0)
			Spec_factor = pow( dot( R, V_pos-Eye_pos ), shininess)
		"""
		'''which, as we can see, involves the vertex position in a number 
		of stages of the operation, so requires recalculation all through 
		the rendering operation.
		
		There is, however, a simplified version of Phong Lighting called 
		[http://en.wikipedia.org/wiki/Blinn%E2%80%93Phong_shading_model Blinn-Phong]
		which notes that if we were to do all of our calculations in 
		"eye space", and were to assume that (as is normal), the eye 
		and light coordinates will not change for a rendering pass,
		(note: this limits us to directional lights!) we 
		can use a pre-calculated value which is the bisecting angle
		between the light-vector and the view-vector, called the 
		"half vector" to 
		perform approximately the same calculation.  With this value:'''
		"""
			// note that in Eye coordinates, Eye_EC_dir == 0,0,-1
			H = normalize( Eye_EC_dir + Light_EC_dir )
			Spec_factor = pow( dot( H, N ), shininess )
		"""
		'''Note: however, that the resulting Spec_factor is not *precisely*
		the same value as the original calculation, so the "shininess"
		exponent must be slightly lower to approximate the value that
		Phong rendering would achieve.  The value is, however, considered
		close to "real world" materials, so the Blinn method is generally 
		preferred to Phong.
		'''
		dLight = """
		vec2 dLight( 
			in vec3 light_pos, // light position
			in vec3 half_light, // half-way vector between light and view
			in vec3 frag_normal, // geometry normal
			in float shininess
		) {
			// returns vec2( ambientMult, diffuseMult )
			float n_dot_pos = max( 0.0, dot( 
				frag_normal, light_pos
			));
			float n_dot_half = 0.0;
			if (n_dot_pos > 0.0) {
				n_dot_half = pow(max(0.0,dot( 
					half_light, frag_normal
				)), shininess);
			}
			return vec2( n_dot_pos, n_dot_half);
		}		
		"""
		'''Since we have an extremely low-polygon model, we would not 
		see our "shininess" effect if we were to render lighting only 
		at each vertex, so we are going to use per-fragment rendering.
		As a result, our vertex shader becomes very simple, just arranging
		for the Normals to be varied across the surface.
		'''
		vertex = compileShader( 
		"""
		attribute vec3 Vertex_position;
		attribute vec3 Vertex_normal;
		
		varying vec3 baseNormal;
		void main() {
			gl_Position = gl_ModelViewProjectionMatrix * vec4( 
				Vertex_position, 1.0
			);
			baseNormal = gl_NormalMatrix * normalize(Vertex_normal);
		}""", GL_VERTEX_SHADER)
		'''The actual lighting calculation is simply adding the various 
		contributors together in order to find the final colour, then 
		clamping the result to the range 0.0 to 1.0.  We could have let 
		OpenGL do this clamping itself, the call is done here simply 
		to illustrate the effect.
		
		Our fragment shader here is extremely simple.  We could
		actually do per-fragment lighting calculations, but it wouldn't
		particularly improve our rendering with simple diffuse shading.
		'''
		fragment = compileShader( dLight + """
		uniform vec4 Global_ambient;
		
		uniform vec4 Light_ambient;
		uniform vec4 Light_diffuse;
		uniform vec4 Light_specular;
		uniform vec3 Light_location;
		
		uniform float Material_shininess;
		uniform vec4 Material_specular;
		uniform vec4 Material_ambient;
		uniform vec4 Material_diffuse;
		
		varying vec3 baseNormal;
		void main() {
			vec3 EC_Light_location = gl_NormalMatrix * Light_location;
			vec3 Light_half = EC_Light_location - vec3( 0,0,-10 );
			vec2 weights = dLight(
				normalize(EC_Light_location),
				normalize(Light_half),
				baseNormal,
				Material_shininess
			);
			
			gl_FragColor = clamp( 
			(
				// global component 
				(Global_ambient * Material_ambient)
				// material's interaction with light's contribution 
				// to the ambient lighting...
				+ (Light_ambient * Material_ambient)
				// material's interaction with the direct light from 
				// the light.
				+ (Light_diffuse * Material_diffuse * weights.x)
				// material's shininess...
				+ (Light_specular * Material_specular * weights.y)
			), 0.0, 1.0);
		}
		""", GL_FRAGMENT_SHADER)
		
		self.shader = compileProgram(vertex,fragment)
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
		for uniform in (
			'Global_ambient',
			'Light_ambient','Light_diffuse','Light_location',
			'Light_specular',
			'Material_ambient','Material_diffuse',
			'Material_shininess','Material_specular',
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
		try:
			self.vbo.bind()
			try:
				'''We add a strong red tinge so you can see the 
				global ambient light's contribution.'''
				glUniform4f( self.Global_ambient_loc, .3,.05,.05,.1 )
				'''In legacy OpenGL we would be using different 
				special-purpose calls to set these variables.'''
				glUniform4f( self.Light_ambient_loc, .2,.2,.2, 1.0 )
				glUniform4f( self.Light_diffuse_loc, .5,.5,.5,1 )
				glUniform4f( self.Light_specular_loc, 1.0,1.0,.5,1 )
				light = array( [0,0,10],'f')
				glUniform3f( self.Light_location_loc, *light )
				
				glUniform4f( self.Material_ambient_loc, .2,.2,.2, 1.0 )
				glUniform4f( self.Material_specular_loc, .8,.8,.8, 1.0 )
				glUniform1f( self.Material_shininess_loc, .8)
				glUniform4f( self.Material_diffuse_loc, .5,.5,.5, 1 )
				'''We only have the two per-vertex attributes'''
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
				'''Need to cleanup, as always.'''
				glDisableVertexAttribArray( self.Vertex_position_loc )
				glDisableVertexAttribArray( self.Vertex_normal_loc )
		finally:
			glUseProgram( 0 )

if __name__ == "__main__":
	MainFunction ( TestContext)
'''Our next tutorial will cover the rest of the Phong rendering 
algorithm, by adding "specular highlights" (shininess) to the 
surface.'''
