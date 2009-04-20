"""Flat rendering mechanism using structural scenegraph observation"""
from OpenGLContext.scenegraph import nodepath
from OpenGL.GL import *
from OpenGLContext.arrays import array, dot
from vrml.vrml97 import nodetypes
from vrml import olist
from vrml.vrml97.transformmatrix import RADTODEG
import weakref,random
from pydispatch.dispatcher import connect

class FlatPass( object ):
	"""Flat rendering pass with a single function to render scenegraph 
	
	Uses structural scenegraph observations to allow the actual
	rendering pass be a simple iteration over the paths known 
	to be active in the scenegraph.
	"""
	passCount = 0
	visible = True 
	transparent = False 
	transform = True
	lighting = True
	lightingAmbient = True
	lightingDiffuse = True
	
	selectNames = False
	selectForced = False

	cache = None
	
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
	def __init__( self, scene, contexts ):
		self.scene = scene 
		self.contexts = contexts
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
			if hasattr( next, 'bind' ):
				for context in self.contexts:
					next.bind( context )
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
		glLoadMatrixd( self.getProjection() )
		glMatrixMode( GL_MODELVIEW )
		matrix = self.getModelView()
		
		bPath = self.currentBackground( )
		if bPath is not None:
			glLoadIdentity()
			glMultMatrixf( vp.quaternion.matrix( dtype='f') )
			bPath.transform(mode, translate=0,scale=0, rotate=1 )
			bPath[-1].Render( mode=mode, clear=(mode.passCount==0) )
		elif mode.passCount == 0:
			### default VRML background is black
			glClearColor(0.0,0.0,0.0,1.0)
			glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )
		
		# okay, now visible presentations
		id = 0
		for path in self.paths.get( nodetypes.Light, ()):
			tmatrix = path.transformMatrix()
			glLoadMatrixd( dot(tmatrix,matrix) )
			path[-1].Light( GL_LIGHT0+id, mode=mode )
			id += 1
			if id >= (context.MAX_LIGHTS-1):
				break
		# opaque-only rendering pass...
		for path in self.paths[ nodetypes.Rendering ]:
			tmatrix = path.transformMatrix()
			glLoadMatrixd( dot(tmatrix,matrix) )
			path[-1].Render( mode=mode )
	
	def __call__( self, context ):
		"""Overall rendering pass interface for the context client"""
		mode = self 
		vp = context.getViewPlatform()
		# These values are temporarily stored locally, we are 
		# in the context lock, so we're not causing conflicts
		self.context = context
		self.cache = context.cache
		self.projection = vp.viewMatrix()
		self.viewport = context.getViewPort()
		self.modelView = vp.modelMatrix()
		
		# We're here setting up legacy OpenGL settings 
		# eventually these will be uniform setups...
		self.Render( context, self )
		return True # flip yes, for now we always flip...

	def getProjection (self):
		"""Retrieve the projection matrix for the rendering pass"""
		return self.projection
	def getViewport (self):
		"""Retrieve the viewport parameters for the rendering pass"""
		return self.viewport
	def getModelView( self ):
		"""Retrieve the base model-view matrix for the rendering pass"""
		return self.modelView

