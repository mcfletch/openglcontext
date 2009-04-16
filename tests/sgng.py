#! /usr/bin/env python
'''Simple demo of a rotating image mapped to a square
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext import visitor
from OpenGLContext.events.timer import Timer
from OpenGL.GL import *
from OpenGLContext.arrays import array, dot
from vrml.vrml97 import nodetypes

scene = sceneGraph(
	children = [
		Transform(
			DEF = "pivot",
			children = [
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
				)
			],
		),
		PointLight(
			location = (0,0,8),
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
		self.paths = visitor.find( scene, nodetypes.Rendering )
	def Render( self, mode=None ):
		"""Render the scene via paths instead of sg"""
		matrix = self.getViewPlatform().matrix()
		# clear the projection matrix set up by legacy sg
		glMatrixMode( GL_PROJECTION )
		glLoadIdentity()
		glMatrixMode( GL_MODELVIEW )
		glLoadMatrixf( matrix )
		for path in self.paths:
			tmatrix = path.transformMatrix()
			glPushMatrix()
			glMultMatrixd( tmatrix )
			path[-1].Render( mode=mode )
			glPopMatrix()
	def OnTimerFraction( self, event ):
		"""Modify the node"""
		self.trans.rotation = 0,0,1,(self.rot*event.fraction())
	

if __name__ == "__main__":
	MainFunction ( TestContext)

