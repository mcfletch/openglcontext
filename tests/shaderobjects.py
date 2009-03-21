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
	'./resources/toon.vert.txt',
]
fragment_shaders = [
	'./resources/toon.frag.txt',
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
									url = vert,
									type='VERTEX',
								),
								GLSLShader( 
									DEF = 'Frag_SHADER_%s'%(i),
									url = frag,
									type='FRAGMENT',
								),
							],
						),
					],
				)
			)
		self.shaders.extend([
			
		])
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
			print shader.toString()


if __name__ == "__main__":
	MainFunction ( TestContext)

