#! /usr/bin/env python
'''Simple demo of a rotating image mapped to a square
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph import nodepath
from OpenGLContext import visitor
from OpenGLContext.events.timer import Timer
from OpenGL.GL import *
from OpenGLContext.arrays import array, dot
from OpenGLContext.passes import flat
from vrml.vrml97 import nodetypes
from vrml import olist
from vrml.vrml97.transformmatrix import RADTODEG
import weakref,random
from pydispatch.dispatcher import connect

scene = sceneGraph(
	children = [
		Transform(
			DEF = "pivot",
			children = [
				Switch(
					whichChoice = 0,
					choice = [
						Shape(
							geometry = IndexedFaceSet(
								coord = Coordinate(
									point = [[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]],
								),
								coordIndex = [ 0,1,2,3 ],
								texCoord = TextureCoordinate(
									point = [[0,0],[1,0],[1,1],[0,1]],
								),
								texCoordIndex = [0,1,2,3 ],
							),
							appearance = Appearance(
								texture = ImageTexture(
									url = "nehe_glass.bmp",
								),
							),
						),
						Shape(
							geometry = Teapot(),
							appearance = Appearance(
								texture = ImageTexture(
									url = "nehe_glass.bmp",
								),
							),
						),
					],
				),
			],
		),
		PointLight(
			color = (1,0,0),
			location = (4,4,8),
		),
		Group(),
		CubeBackground(
			backUrl = "pimbackground_BK.jpg",
			frontUrl = "pimbackground_FR.jpg",
			leftUrl = "pimbackground_RT.jpg",
			rightUrl = "pimbackground_LF.jpg",
			topUrl = "pimbackground_UP.jpg",
			bottomUrl = "pimbackground_DN.jpg",
		),
	],
)

		

class TestContext( BaseContext ):
	rot = 6.283
	initialPosition = (0,0,3)
	def OnInit( self ):
		sg = scene
		self.trans = sg.children[0]
		self.time = Timer( duration = 8.0, repeating = 1 )
		self.time.addEventHandler( "fraction", self.OnTimerFraction )
		self.time.register (self)
		self.time.start ()
		self.renderPasses = self.performer = flat.FlatPass( scene, [self] )
		self.addEventHandler( "keypress", name="a", function = self.OnAdd)
		self.MAX_LIGHTS = glGetIntegerv( GL_MAX_LIGHTS )
	def OnTimerFraction( self, event ):
		"""Modify the node"""
		self.trans.rotation = 0,0,1,(self.rot*event.fraction())
	def OnAdd( self, event ):
		"""Add a new box to the scene"""
		children = scene.children[2].children
		if len(children) > 20:
			children[:] = []
		else:
			cube = 10
			position = ( 
				(random.random()-.5)*cube,
				(random.random()-.5)*cube,
				(random.random()-.5)*cube 
			)
			color = (random.random(),random.random(),random.random())
			children.append( Transform(
				translation = position,
				children = [
					Shape(
						geometry = Teapot( size=.2),
						appearance = Appearance(
							material=Material( 
#								diffuseColor = color,
								diffuseColor = (.8,.8,.8),
							)
						),
					),
				],
			))

if __name__ == "__main__":
	import cProfile
	cProfile.run( "MainFunction ( TestContext)", 'new.profile' )


