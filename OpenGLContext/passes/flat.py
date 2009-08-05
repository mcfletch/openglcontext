"""Flat rendering mechanism using structural scenegraph observation"""
from OpenGLContext.scenegraph import nodepath,switch
from OpenGL.GL import *
from OpenGL.GLU import gluUnProject
from OpenGLContext.arrays import array, dot
from OpenGLContext import frustum
from OpenGLContext.debug.logs import getTraceback
from vrml.vrml97 import nodetypes
from vrml import olist
from vrml.vrml97.transformmatrix import RADTODEG
import weakref,random, sys, ctypes, logging
from pydispatch.dispatcher import connect
log = logging.getLogger( 'OpenGLContext.passes.flat' )

if sys.maxint > 2L<<32:
	BIGINTS = True 
else:
	BIGINTS = False
	
class SGObserver( object ):
	"""Observer of a scenegraph that creates a flat set of paths 
	
	Uses dispatcher watches to observe any changes to the (rendering)
	structure of a scenegraph and uses it to update an internal set 
	of paths for all renderable objects in the scenegraph.
	"""
	INTERESTING_TYPES = []
	def __init__( self, scene, contexts ):
		"""Initialize the FlatPass for this scene and set of contexts 
		
		scene -- the scenegraph to manage as a flattened hierarchy
		contexts -- set of (weakrefs to) contexts to be serviced, 
			normally is a reference to Context.allContexts
		"""
		self.scene = scene 
		self.contexts = contexts
		self.paths = {
		}
		self.nodePaths = {}
		if scene:
			self.integrate( scene )
		connect(
			self.onChildAdd,
			signal = olist.OList.NEW_CHILD_EVT,
		)
		connect(
			self.onChildRemove,
			signal = olist.OList.DEL_CHILD_EVT,
		)
		connect(
			self.onSwitchChange,
			signal = switch.SWITCH_CHANGE_SIGNAL,
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
					context = context()
					if context is not None:
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
	def onSwitchChange( self, sender, value ):
		for path in self.npFor( sender ):
			for childPath in path.iterchildren():
				if childPath[-1] is not value:
					childPath.invalidate()
			self.integrate( value, path )
		self.purge()
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

class FlatPass( SGObserver ):
	"""Flat rendering pass with a single function to render scenegraph 
	
	Uses structural scenegraph observations to allow the actual
	rendering pass be a simple iteration over the paths known 
	to be active in the scenegraph.
	
	Rendering Attributes:
	
		visible -- whether we are currently rendering a visible pass
		transparent -- whether we are currently doing a transparent pass
		lighting -- whether we currently are rendering a lit pass
		context -- context for which we are rendering 
		cache -- cache of the context for which we are rendering 
		projection -- projection matrix of current view platform
		modelView -- model-view matrix of current view platform 
		viewport -- 4-component viewport definition for current context 
		frustum -- viewing-frustum definition for current view platform
		MAX_LIGHTS -- queried maximum number of lights
		

		passCount -- not used, always set to 0 for code that expects
			a passCount to be available.
		transform -- ignored, legacy code only 

	"""
	passCount = 0
	visible = True 
	transparent = False 
	transform = True
	lighting = True
	lightingAmbient = True
	lightingDiffuse = True
	
	# this are now obsolete...
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
	
	def renderSet( self, matrix ):
		"""Calculate ordered rendering set to display"""
		# ordered set of things to work with...
		
		# TODO: use child.visible here with occlusion queries
		# to filter toRender down...
		toRender = []
		for path in self.paths.get( nodetypes.Rendering, ()):
			tmatrix = path.transformMatrix()
			mvmatrix = dot(tmatrix,matrix)
			sortKey = path[-1].sortKey( self, tmatrix )
			if hasattr( path[-1], 'boundingVolume' ):
				bvolume = path[-1].boundingVolume( self )
			else:
				bvolume = None
			toRender.append( (sortKey, mvmatrix,tmatrix,bvolume, path ) )
		# TODO: allow 
		toRender = self.frustumVisibilityFilter( toRender )
		toRender.sort( key = lambda x: x[0])
		return toRender
	def frustumVisibilityFilter( self, records ):
		"""Filter records for visibility using frustum planes
		
		This does per-object culling based on frustum lookups
		rather than object query values.  It should be fast 
		*if* the frustcullaccel module is available, if not 
		it will be dog-slow.
		"""
		result = []
		frustum = self.frustum
		for record in records:
			(key,mv,tm,bv,path) = record 
			if bv is not None:
				if bv.visible( 
					frustum, tm,
					occlusion=False,
					mode=self
				):
					result.append( record )
			else:
				result.append( record )
		return result
	
	def Render( self, context, mode ):
		"""Render the geometry attached to this flat-renderer's scenegraph"""
		vp = context.getViewPlatform()
		# clear the projection matrix set up by legacy sg
		glMatrixMode( GL_PROJECTION )
		glLoadMatrixd( self.getProjection() )
		glMatrixMode( GL_MODELVIEW )
		matrix = self.getModelView()
		self.matrix = matrix
		glLoadIdentity()

		toRender = self.renderSet( matrix )
		
		events = context.getPickEvents()
		if events or mode.context.DEBUG_SELECTION:
			self.selectRender( mode, toRender, events )
			events.clear()
		glMatrixMode( GL_PROJECTION )
		glLoadMatrixd( self.getProjection() )
		glMatrixMode( GL_MODELVIEW )
		matrix = self.getModelView()
		if not mode.context.DEBUG_SELECTION:
			glLoadIdentity()
			self.matrix = matrix
			self.visible = True
			self.transparent = False 
			self.lighting = True
			self.textured = True 
			
			self.legacyBackgroundRender( vp,matrix )
			# Set up generic "geometric" rendering parameters
			glDisable( GL_CULL_FACE )
			glFrontFace( GL_CCW )
			glEnable(GL_DEPTH_TEST)
			glEnable(GL_LIGHTING)
			glDepthFunc(GL_LESS)
			glEnable(GL_CULL_FACE)
			glCullFace(GL_BACK)
			
			self.legacyLightRender( matrix )
			transparentSetup = False
			
			for key,mvmatrix,tmatrix,bvolume,path in toRender:
				self.matrix = mvmatrix
				glLoadMatrixd( mvmatrix )
				
				self.transparent = key[0]
				if key[0] != transparentSetup:
					glEnable(GL_BLEND);
					glBlendFunc(GL_ONE_MINUS_SRC_ALPHA,GL_SRC_ALPHA, )
					glDepthMask( 0 )
				try:
					if key[0]:
						function = path[-1].RenderTransparent
					else:
						function = path[-1].Render
					function( mode=self )
				except Exception, err:
					log.error(
						"""Failure in %s: %s""",
						function,
						getTraceback( err ),
					)
		glDisable(GL_BLEND);
		glEnable(GL_DEPTH_TEST);
		glDepthMask( 1 ) # allow updates to the depth buffer
		if context.frameCounter.display:
			context.frameCounter.Render( context )
		context.SwapBuffers()
		self.matrix = matrix
	
	def legacyBackgroundRender( self, vp,matrix ):
		"""Do legacy background rendering"""
		bPath = self.currentBackground( )
		if bPath is not None:
			glMultMatrixf( vp.quaternion.matrix( dtype='f') )
			bPath.transform(self, translate=0,scale=0, rotate=1 )
			bPath[-1].Render( mode=self, clear=True )
		else:
			### default VRML background is black
			glClearColor(0.0,0.0,0.0,1.0)
			glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )
	
	def legacyLightRender( self, matrix ):
		"""Do legacy light-rendering operation"""
		# okay, now visible presentations
		for remaining in range(0,self.MAX_LIGHTS-1):
			glDisable( GL_LIGHT0 + remaining )
		id = 0
		for path in self.paths.get( nodetypes.Light, ()):
			tmatrix = path.transformMatrix()
			
			localMatrix = dot(tmatrix,matrix)
			self.matrix = localMatrix
			glLoadMatrixd( localMatrix )
			
			path[-1].Light( GL_LIGHT0+id, mode=self )
			id += 1
			if id >= (self.MAX_LIGHTS-1):
				break
		if not id:
			# default VRML lighting...
			from OpenGLContext.scenegraph import light
			l = light.DirectionalLight( direction = (0,0,-1.0))
			glLoadMatrixd( matrix )
			l.Light( GL_LIGHT0, mode = self )
		self.matrix = matrix
	
	def selectRender( self, mode, toRender, events ):
		"""Render each path to color buffer
		
		We render all geometry as non-transparent geometry with 
		unique colour values for each object.  We should be able 
		to handle up to 2**24 objects before that starts failing.
		"""
		glClear( GL_DEPTH_BUFFER_BIT|GL_COLOR_BUFFER_BIT )
		glDisable( GL_LIGHTING )
		glEnable( GL_COLOR_MATERIAL )
		
		self.visible = False
		self.transparent = False 
		self.lighting = False
		self.textured = False 
		
		matrix = self.matrix
		map = {}
		
		pickPoints = {}
		for event in events.values():
			key = tuple(event.getPickPoint())
			pickPoints.setdefault( key, []).append( event )
		
		idHolder = array( [0,0,0,0], 'b' )
		idSetter = idHolder.view( '<I' )
		for id,(key,mvmatrix,tmatrix,bvolume,path) in enumerate(toRender):
			id += 50
			idSetter[0] = id
			glColor4bv( idHolder )
			self.matrix = mvmatrix
			glLoadMatrixd( mvmatrix )
			path[-1].Render( mode=self )
			map[id] = path 
		for point,eventSet in pickPoints.items():
			# get the pixel colour (id) under the cursor.
			pixel = glReadPixels( point[0],point[1],1,1,GL_RGBA,GL_BYTE )
			pixel = long( pixel.view( '<I' )[0][0][0] )
			paths = map.get( pixel, [] )
			event.setObjectPaths( [paths] )
			# get the depth value under the cursor...
			pixel = glReadPixels( 
				point[0],point[1],1,1,GL_DEPTH_COMPONENT,GL_FLOAT 
			)
			event.viewCoordinate = point[0],point[1],pixel[0][0]
			event.modelViewMatrix = matrix
			event.projectionMatrix = self.projection
			event.viewport = self.viewport
			if hasattr( mode.context, 'ProcessEvent'):
				mode.context.ProcessEvent( event )
		glColor4f( 1.0,1.0,1.0, 1.0)
		glDisable( GL_COLOR_MATERIAL )
#		glEnable( GL_LIGHTING )
		
	MAX_LIGHTS = -1
	def __call__( self, context ):
		"""Overall rendering pass interface for the context client"""
		mode = self 
		vp = context.getViewPlatform()
		# These values are temporarily stored locally, we are 
		# in the context lock, so we're not causing conflicts
		if self.MAX_LIGHTS == -1:
			self.MAX_LIGHTS = glGetIntegerv( GL_MAX_LIGHTS )
		self.context = context
		self.cache = context.cache
		self.projection = vp.viewMatrix()
		self.viewport = (0,0) + context.getViewPort()
		self.modelView = vp.modelMatrix()
		# TODO: calculate from view platform instead
		self.frustum = frustum.Frustum.fromViewingMatrix(
			dot(self.modelView,self.projection),
			normalize = 1
		)
		
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

