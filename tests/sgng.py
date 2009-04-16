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
from vrml.vrml97 import nodetypes
from vrml import olist
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
			location = (0,0,8),
		),
		Group(),
	],
)

class Performer( object ):
	"""Object which does performer-style optimizations of scenegraph"""
	INTERESTING_TYPES = [
		nodetypes.Rendering,
		nodetypes.Bindable,
		nodetypes.Light,
		nodetypes.Traversable,
	]
	def __init__( self, scene ):
		self.scene = scene 
		self.paths = {
		}
		self.nodePaths = {}
		self.integrate( scene )
		connect(
			self.onChildAdd,
			signal = olist.OList.NEW_CHILD_EVT,
		)
		connect(
			self.onChildRemove,
			signal = olist.OList.DEL_CHILD_EVT,
		)
	def integrate( self, node, parentPath=None ):
		"""Integrate any children of node which are of interest"""
		if parentPath is None:
			parentPath = nodepath.NodePath( [] )
		todo = [ (node,parentPath) ]
		while todo:
			next,parents = todo.pop(0)
			path = parents + next 
			np = self.npFor( next )
			np.append( path )
			after = self.npFor(next)
			for typ in self.INTERESTING_TYPES:
				if isinstance( next, typ ):
					self.paths.setdefault( typ, []).append( path )
			if hasattr(next, 'renderedChildren'):
				# watch for next's changes...
				for child in next.renderedChildren( ):
					todo.append( (child,path) )
	def npFor( self, node ):
		"""For some reason setdefault isn't working for the weakkeydict"""
		current = self.nodePaths.get( id(node) )
		if current is None:
			self.nodePaths[id(node)] = current = []
		return current
	def onChildAdd( self, sender, value ):
		"""Sender has a new child named value"""
		if hasattr( sender, 'renderedChildren' ):
			children = sender.renderedChildren()
			if value in children:
				for path in self.npFor( sender ):
					self.integrate( value, path )
	def onChildRemove( self, sender, value ):
		"""Invalidate all paths where sender has value as its child IFF child no longer in renderedChildren"""
		print 'onChildRemove'
		if hasattr( sender, 'renderedChildren' ):
			children = sender.renderedChildren()
			if value not in children:
				for path in self.npFor( sender ):
					for childPath in path.iterchildren():
						if childPath[-1] is value:
							childPath.invalidate()
				self.purge()
	def purge( self ):
		"""Purge all references to path"""
		for key,values in self.paths.items():
			filtered = []
			for v in values:
				if not v.broken:
					filtered.append( v )
				else:
					np = self.npFor( v )
					while v in np:
						np.remove( v )
					if not np:
						try:
							del self.nodePaths[id(v)]
						except KeyError, err:
							pass
			self.paths[key][:] = filtered

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
		self.performer = Performer( scene )
		self.addEventHandler( "keypress", name="a", function = self.OnAdd)
	def Render( self, mode=None ):
		"""Render the scene via paths instead of sg"""
		matrix = self.getViewPlatform().matrix()
		# clear the projection matrix set up by legacy sg
		glMatrixMode( GL_PROJECTION )
		glLoadIdentity()
		glMatrixMode( GL_MODELVIEW )
		for path in self.performer.paths[ nodetypes.Rendering ]:
			tmatrix = path.transformMatrix()
			glLoadMatrixd( dot(tmatrix,matrix) )
			path[-1].Render( mode=mode )
	def OnTimerFraction( self, event ):
		"""Modify the node"""
		self.trans.rotation = 0,0,1,(self.rot*event.fraction())
	def OnAdd( self, event ):
		"""Add a new box to the scene"""
		children = scene.children[2].children
		if len(children) > 128:
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
								diffuseColor = color,
							)
						),
					),
				],
			))

if __name__ == "__main__":
	MainFunction ( TestContext)

