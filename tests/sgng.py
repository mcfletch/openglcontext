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

class Performer( object ):
	"""Object which does performer-style optimizations of scenegraph"""
	INTERESTING_TYPES = [
		nodetypes.Rendering,
		nodetypes.Bindable,
		nodetypes.Light,
		nodetypes.Traversable,
		nodetypes.Background,
		nodetypes.TimeDependent,
		nodetypes.Fog,
		nodetypes.Viewpoint,
		nodetypes.NavigationInfo,
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
	def currentBackground( self ):
		"""Find our current background node"""
		paths = self.paths.get( nodetypes.Background, () )
		for background in paths:
			if background[-1].bound:
				return background
		if paths:
			current = paths[0]
			current[-1].bound = 1
			return current 
		return None
		
	def Render( self, context, mode ):
		"""Render the geometry attached to this performer's scenegraph"""
		vp = context.getViewPlatform()
		# clear the projection matrix set up by legacy sg
		glMatrixMode( GL_PROJECTION )
		glLoadMatrixd( vp.viewMatrix() )
		glMatrixMode( GL_MODELVIEW )
		matrix = vp.modelMatrix()
		
		bPath = self.currentBackground( )
		if bPath is not None:
			glLoadIdentity()
			x,y,z,r = vp.quaternion.XYZR()
			glRotate( r*RADTODEG, x,y,z )
			bPath.transform(visitor, translate=0,scale=0, rotate=1 )
			bPath[-1].Render( mode=mode, clear=(mode.passCount==0) )
		
		id = 0
		for path in self.paths.get( nodetypes.Light, ()):
			tmatrix = path.transformMatrix()
			glLoadMatrixd( dot(tmatrix,matrix) )
			path[-1].Light( GL_LIGHT0+id, mode=mode )
			id += 1
			if id >= (context.MAX_LIGHTS-1):
				break
		
		for path in self.paths[ nodetypes.Rendering ]:
			tmatrix = path.transformMatrix()
			glLoadMatrixd( dot(tmatrix,matrix) )
			path[-1].Render( mode=mode )
		

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
		self.MAX_LIGHTS = glGetIntegerv( GL_MAX_LIGHTS )
	def Render( self, mode=None ):
		"""Render the scene via paths instead of sg"""
		self.performer.Render( self, mode=mode )
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


