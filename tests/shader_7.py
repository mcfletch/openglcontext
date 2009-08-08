#! /usr/bin/env python
'''=Multiple Lights, GLSL Looping and Structures=

[shader_7.py-screen-0001.png Screenshot]

This tutorial builds on earlier tutorials by adding:

	* Multiple Lights
	* GLSL Structures (for defining a Material)
	* GLSL Looping (for processing multiple lights)

Until now, our tutorials have had a single light.  This tutorial 
is going to demonstrate how to use simple looping in GLSL to 
iterate over a set of lights applying our existing rendering 
algorithm to each defined light.

We're also going to quickly demonstrate the use of GLSL structures 
to bind together similar information into namespaces for easier 
reference.
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL.shaders import *
from OpenGLContext.scenegraph.basenodes import Sphere

class TestContext( BaseContext ):
	"""Demonstrates use of attribute types in GLSL
	"""
	def OnInit( self ):
		"""Initialize the context"""
		
		materialStruct = """
		struct Material {
			vec4 ambient;
			vec4 diffuse;
			vec4 specular;
			float shininess;
		};
		"""
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
			if (n_dot_pos > -.05) {
				n_dot_half = pow(max(0.0,dot( 
					half_light, frag_normal
				)), shininess);
			}
			return vec2( n_dot_pos, n_dot_half);
		}		
		"""
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
		fragment = compileShader( 
			dLight + materialStruct + """
		uniform Material material;
		uniform vec4 Global_ambient;
		// see below for why we aren't using an array of 
		// LightSource structures...
		uniform vec4 lights[ 12 ]; // 3 possible lights 4 vec4's each 
		
		varying vec3 baseNormal;
		void main() {
			vec4 fragColor = Global_ambient * material.ambient;
			
			int AMBIENT = 0;
			int DIFFUSE = 1;
			int SPECULAR = 2;
			int POSITION = 3;
			
			int i;
			for (i=0;i<12;i=i+4) {
				// normalized eye-coordinate Light location
				vec3 EC_Light_location = normalize(
					gl_NormalMatrix * lights[i+POSITION].xyz
				);
				// half-vector calculation 
				vec3 Light_half = normalize(
					EC_Light_location - vec3( 0,0,-1 )
				);
				vec2 weights = dLight(
					EC_Light_location,
					Light_half,
					baseNormal,
					material.shininess
				);
				fragColor = (
					fragColor 
					+ (lights[i+AMBIENT] * material.ambient)
					+ (lights[i+DIFFUSE] * material.diffuse * weights.x)
					+ (lights[i+SPECULAR] * material.specular * weights.y)
				);
			}
			gl_FragColor = fragColor;
		}
		""", GL_FRAGMENT_SHADER)
		'''==Why not an Array of Structures?==

		Originally this tutorial was going to use an array of LightSource
		structures as a Uniform, with the components of the structures 
		specified with separate calls to glUniform4f.  Problem is, that 
		doesn't actually *work*.  While glUniform *should* be able to 
		handle array-of-structure indexing, it doesn't actually support 
		this type of operation in the real world. The built-in 
		gl_LightSourceParameters are an array-of-structures, but 
		apparently the GL implementations consider this a special case,
		rather than a generic type of functionality to be supported.

		An array-of-structures value looks like this when declared in GLSL:
		'''
		lightStruct = """
		// NOTE: this does not work, it compiles, but you will 
		// not be able to fill in the individual members...
		struct LightSource {
			vec4 ambient;
			vec4 diffuse;
			vec4 specular;
			vec4 position;
		};
		uniform LightSource lights[3];
		"""
		'''But when you attempt to retrieve the location for the Uniform 
		via:
		
			glGetUniformLocation( shader, 'lights[0].ambient' )
		
		you will always get a -1 (invalid) location.
		OpenGL 3.1 introduced the concept of Uniform Buffers, which allow 
		for packing Uniform data into VBO storage, but it's not yet clear
		whether they will support array-of-structure specification.
		'''
		self.shader = compileProgram(vertex,fragment)
		self.coords,self.indices,self.count = Sphere( 
			radius = 1 
		).compile()
		self.uniform_locations = {}
		for uniform,value in self.UNIFORM_VALUES:
			location = glGetUniformLocation( self.shader, uniform )
			if location in (None,-1):
				print 'Warning, no uniform: %s'%( uniform )
			self.uniform_locations[uniform] = location
		for attribute in (
			'Vertex_position','Vertex_normal',
		):
			location = glGetAttribLocation( self.shader, attribute )
			if location in (None,-1):
				print 'Warning, no attribute: %s'%( uniform )
			setattr( self, attribute+ '_loc', location )
		self.uniform_locations['lights'] = glGetUniformLocation( 
			self.shader, 'lights' 
		)

	UNIFORM_VALUES = [
		('Global_ambient',(.05,.05,.05,1.0)),
		('material.ambient',(.2,.2,.2,1.0)),
		('material.diffuse',(.5,.5,.5,1.0)),
		('material.specular',(.8,.8,.8,1.0)),
		('material.shininess',(.995,)),
	]
	LIGHTS = array([
		x[1] for x in [
			('lights[0].ambient',(.05,.05,.05,1.0)),
			('lights[0].diffuse',(.3,.3,.3,1.0)),
			('lights[0].specular',(1.0,0.0,0.0,1.0)),
			('lights[0].position',(4.0,2.0,10.0,1.0)),
			('lights[1].ambient',(.05,.05,.05,1.0)),
			('lights[1].diffuse',(.3,.3,.3,1.0)),
			('lights[1].specular',(0.0,1.0,0.0,1.0)),
			('lights[1].position',(-4.0,2.0,10.0,1.0)),
			('lights[2].ambient',(.05,.05,.05,1.0)),
			('lights[2].diffuse',(.3,.3,.3,1.0)),
			('lights[2].specular',(0.0,0.0,1.0,1.0)),
			('lights[2].position',(-4.0,2.0,-10.0,1.0)),
		]
	], 'f')
	def Render( self, mode = None):
		"""Render the geometry for the scene."""
		BaseContext.Render( self, mode )
		glUseProgram(self.shader)
		try:
			self.coords.bind()
			self.indices.bind()
			stride = self.coords.data[0].nbytes
			try:
				glUniform4fv( 
					self.uniform_locations['lights'],
					12,
					self.LIGHTS
				)
				for uniform,value in self.UNIFORM_VALUES:
					location = self.uniform_locations.get( uniform )
					if location not in (None,-1):
						if len(value) == 4:
							glUniform4f( location, *value )
						elif len(value) == 3:
							glUniform3f( location, *value )
						elif len(value) == 1:
							glUniform1f( location, *value )
				glEnableVertexAttribArray( self.Vertex_position_loc )
				glEnableVertexAttribArray( self.Vertex_normal_loc )
				glVertexAttribPointer( 
					self.Vertex_position_loc, 
					3, GL_FLOAT,False, stride, self.coords
				)
				glVertexAttribPointer( 
					self.Vertex_normal_loc, 
					3, GL_FLOAT,False, stride, self.coords+(5*4)
				)
				glDrawElements(
					GL_TRIANGLES, self.count,
					GL_UNSIGNED_SHORT, self.indices
				)
			finally:
				self.coords.unbind()
				self.indices.unbind()
				glDisableVertexAttribArray( self.Vertex_position_loc )
				glDisableVertexAttribArray( self.Vertex_normal_loc )
		finally:
			glUseProgram( 0 )

if __name__ == "__main__":
	MainFunction ( TestContext)
