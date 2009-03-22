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

shaders = [
	Shader( objects = [o], DEF='Shader_%s'%(i,) )
	for i,o in enumerate([
	GLSLObject(
		uniforms = [
			FloatUniform2f(name = 'henry',value = [0,1]),
		],
		shaders = [
			GLSLShader( url = './resources/toon.vert.txt', type='VERTEX'),
			GLSLShader( url = './resources/toon.frag.txt', type='FRAGMENT'),
		],
	),
	GLSLObject(
		uniforms = [
			FloatUniform1f(name="Shininess", value=.9 ),
			FloatUniform1f(name="Diffuse", value=.9 ),
			FloatUniform1f(name="Specular", value=.8 ),
			
			FloatUniform1f(name="MaxIterations", value=10 ),
			FloatUniform2f(name="Center",value=(0,0), DEF='MAND_CENT'),
			FloatUniform1f(name="Zoom",value=1.0, DEF='MAND_ZOOM' ),
			FloatUniform3f(name="InnerColor",value=(1,0,0)),
			FloatUniform3f(name="OuterColor1",value=(0,1,0)),
			FloatUniform3f(name="OuterColor2",value=(0,0,1)),
		],
		shaders = [
			GLSLShader( 
				url = './resources/CH18-mandel.vert.txt', type='VERTEX'
			),
			GLSLShader( 
				url = './resources/CH18-mandel.frag.txt', type='FRAGMENT'
			),
		],
	)
	])
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
		self.shaders = shaders
		self.shapes = [
			Shape(
				appearance = self.shaders[0],
				geometry = Sphere( radius = 2.0 ),
			),
			Shape(
				appearance = self.shaders[0],
				geometry = Teapot( size = .75 ),
			),
			Shape(
				appearance = self.shaders[0],
				geometry = Box( size=(3,3,3) ),
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
				Transform(
					translation = (5,0,3),
					children = [
						self.shapes[2]
					],
				),
			],
		)
		self.time = Timer( duration = 30.0, repeating = 1 )
		self.time.addEventHandler( "fraction", self.OnTimerFraction )
		self.time.register (self)
		self.time.start ()
		print 'press "n" for next shader'
		self.addEventHandler( "keypress", name="n", function = self.OnNext)
		
		# MANDELBROT explorer...
		print 'Explore Orange-book mandelbrot with:\n   asdw (center) zx (zoom) and rf (iterations)'
		self.addEventHandler( "keypress", name="a", function = self.OnMand)
		self.addEventHandler( "keypress", name="d", function = self.OnMand)
		self.addEventHandler( "keypress", name="s", function = self.OnMand)
		self.addEventHandler( "keypress", name="w", function = self.OnMand)
		self.addEventHandler( "keypress", name="z", function = self.OnMand)
		self.addEventHandler( "keypress", name="x", function = self.OnMand)
		self.addEventHandler( "keypress", name="r", function = self.OnMand)
		self.addEventHandler( "keypress", name="f", function = self.OnMand)
		
	def OnTimerFraction( self, event ):
		r = event.fraction()
		self.sg.children[0].rotation = [0,1,0,r * math.pi *2]
	def OnNext( self, event ):
		self.current_shader += 1
		shader = self.shaders[ self.current_shader % len(self.shaders) ]
		for shape in self.shapes:
			shape.appearance = shader 
			#print shader.toString()
	def OnMand( self, event ):
		shader = self.shaders[1]
		zoom = shader.objects[0].getVariable( 'Zoom' )
		center = shader.objects[0].getVariable( 'Center' )
		iterations = shader.objects[0].getVariable( 'MaxIterations' )
		if event.name == 'z':
			zoom.value = zoom.value * .95
			print 'zoom value', zoom.value
		elif event.name == 'x':
			zoom.value = zoom.value * 1.05
			print 'zoom value', zoom.value
		elif event.name == 'r':
			iterations.value += 1
		elif event.name == 'f':
			iterations.value -= 1
			if iterations.value[0] == 0:
				iterations.value = 1
		directions = { 'a':(-1,0),'d':(1,0),'w':(0,1),'s':(0,-1) }
		if directions.has_key( event.name ):
			step = zoom.value / 10.0
			vec = array(directions[event.name],'f') * step 
			center.value = center.value + vec
			print 'new center', center.value
		

if __name__ == "__main__":
	MainFunction ( TestContext)

