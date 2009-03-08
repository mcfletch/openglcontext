#! /usr/bin/env python
'''Tests rendering using the ARB shader objects extension...
'''
#import OpenGL 
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from OpenGLContext.arrays import array
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.shaders import *
import time, sys,logging,math
log = logging.getLogger( 'shaderobjects' )
log.warn( 'Context %s',  BaseContext )

vertex_shaders = [
	#TOON
	'''
	varying vec3 normal;
	void main() {
		normal = gl_NormalMatrix * gl_Normal;
		gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
	}
	''',
]
fragment_shaders = [
	#TOON
	'''
	varying vec3 normal;
	void main() {
		float intensity;
		vec4 color;
		vec3 n = normalize(normal);
		vec3 l = normalize(gl_LightSource[0].position).xyz;
	
		// quantize to 5 steps (0, .25, .5, .75 and 1)
		intensity = (floor(dot(l, n) * 4.0) + 1.0)/4.0;
		color = vec4(intensity*1.0, intensity*0.5, intensity*0.5,
			intensity*1.0);
	
		gl_FragColor = color;
	}
	''',
]


class TestContext( BaseContext ):
	rotation = 0.00
	
	current_shader = 0
	
	def OnInit( self ):
		"""Scene set up and initial processing"""
		t = Transform(
			children = [
				PointLight(
					location = (1,4,10),
				),
			],
		)
		self.shaders = []
		for i,(vert,frag) in enumerate(zip( vertex_shaders,fragment_shaders)):
			self.shaders.append(
				Shader(
					objects = [
						GLSLObject(
							shaders = [
								GLSLShader( 
									DEF = 'Vert_SHADER_%s'%(i),
									source = vert,
									type='VERTEX',
								),
								GLSLShader( 
									DEF = 'Frag_SHADER_%s'%(i),
									source = frag,
									type='FRAGMENT',
								),
							],
						),
					],
				)
			)
		self.shapes = [
			Shape(
				appearance = self.shaders[0],
				geometry = Sphere( radius = 2.0 ),
			),
			Shape(
				appearance = self.shaders[0],
				geometry = Sphere( radius = .75 ),
			),
		]
		self.sg = sceneGraph(
			children = [
				Transform(
					DEF = 'scene',
					children= [
						self.shapes[0],
						Transform(
							translation = (-3,0,4),
							children = [
								self.shapes[1]
							],
						),
						Transform(
							translation = (-2,0,6),
							children = [
								Shape(
									appearance = Appearance(
										material = Material( diffuseColor = (0,0,1)),
									),
									geometry = Sphere( radius = .25 ),
								),
							],
						),
					],
				),
				t,
			],
		)
		self.time = Timer( duration = 30.0, repeating = 1 )
		self.time.addEventHandler( "fraction", self.OnTimerFraction )
		self.time.register (self)
		self.time.start ()
		self.addEventHandler( "keypress", name="n", function = self.OnNext)
	def OnTimerFraction( self, event ):
		r = event.fraction()
		self.sg.children[0].rotation = [0,1,0,r * math.pi *2]
	def OnNext( self, event ):
		self.current_shader += 1
		shader = self.shaders[ self.current_shader % len(self.shaders) ]
		for shape in self.shapes:
			shape.appearance = shader 


if __name__ == "__main__":
	MainFunction ( TestContext)

