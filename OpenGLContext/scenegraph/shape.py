"""Renderable geometry composed of a geometry object with applied appearance"""
from OpenGL.GL import *
from vrml.vrml97 import basenodes
from OpenGLContext.scenegraph import boundingvolume, polygonsort
from OpenGLContext.debug.logs import visitor_log
from OpenGLContext.arrays import array
import traceback, cStringIO
LOCAL_ORIGIN = array( [[0,0,0,1.0]], 'f')

class Shape( basenodes.Shape ):
	"""Defines renderable objects by binding Appearance to a geometry node

	The Shape node defines a renderable geometric object. Basically
	it is a binding of a particular geometry node to a particular
	appearance node.  The Shape node coordinates the rendering of
	the appearance and geometry such that the appearance is applied
	only to the appropriate geometry.

	Attributes of note within the Shape object:

		geometry -- pointer to the geometry object, often an
			arraygeometry object, although potentially a Nurb object,
			or similar geometric primitive.

		appearance -- pointer to the appearance object.  This must
			be an actual Appearance object or None to the default
			appearance.

	Reference:
		http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Shape
	"""
	def Render (self, mode = None):
		"""Do run-time rendering of the Shape for the given mode"""
		if not self.geometry:
			return
		if mode.visible: # anything else...
			if self.appearance:
				lit, textured, alpha, textureToken = self.appearance.render (mode=mode)
				if alpha < 1.0:# is currently somewhat transparent
					if not mode.transparent:
						mode.addTransparent( self )
					if textured:
						# undo the texture setup (since we won't render anything just now)
						self.appearance.renderPost(textureToken, mode=mode)
					return
			else:
				lit = 0
				textured = 0
				glColor3f( 1,1,1 )
			if lit and mode.lighting:
				glEnable(GL_LIGHTING)
			else:
				glDisable(GL_LIGHTING)
			self.geometry.render (lit = lit, textured = textured, mode=mode)
			if textured:
				self.appearance.renderPost(textureToken, mode=mode)
			try:
				glDisable(GL_LIGHTING)
			except GLerror, err:
				# this sometimes throws an error with
				# invalid operation, though it really
				# shouldn't AFAICS (as long as the geometry
				# has called glEnd()).
				if glGetBoolean( GL_LIGHTING ):
					# lighting is still enabled, we want it disabled
					# so tell the programmer about the problem...
					traceback.print_exc( 2 )
		else:
			# by default, just render using the mode's settings
			# (this is only called if visible false, BTW)
			self.geometry.render (
				lit= mode.lighting,
				textured= mode.visible,
				visible = mode.visible,
				mode=mode,
			)
	def RenderTransparent( self, mode ):
		if not self.geometry:
			return False
		textureToken = None
		if self.appearance:
			lit, textured, alpha, textureToken = self.appearance.render ( 
				mode=mode 
			)
		else:
			lit = 0
			textured = 0
			glColor3f( 1,1,1)
		if lit and mode.lighting:
			glEnable(GL_LIGHTING)
		else:
			glDisable(GL_LIGHTING)
		## do the actual work of rendering it transparently...
		self.geometry.render(
			lit = lit, textured = textured, transparent=1, mode=mode
		)
		if self.appearance:
			self.appearance.renderPost( textureToken, mode=mode )
		
	def sortKey( self, mode, matrix ):
		"""Produce the sorting key for this shape's appearance/shaders/etc"""
		# distance calculation...
		distance = polygonsort.distances(
			LOCAL_ORIGIN,
			modelView = matrix,
			projection = mode.getProjection(),
			viewport = mode.getViewport(),
		)[0]
		if self.appearance:
			key = self.appearance.sortKey( mode, matrix )
		else:
			key = (False,[],None)
		if key[0]:
			distance = -distance
		return key[0:2]+ (distance,) + key[1:]

	def boundingVolume( self, mode ):
		"""Create a bounding-volume object for this node

		This is our geometry's boundingVolume, with the
		addition that any dependent volume must be dependent
		on our geometry field.
		"""
		current = boundingvolume.getCachedVolume( self )
		if current:
			return current
		if self.geometry:
			if hasattr( self.geometry, 'boundingVolume'):
				volume = self.geometry.boundingVolume(mode)
			else:
				# is considered always visible
				volume = boundingvolume.UnboundedVolume()
		else:
			# is never visible
			volume = boundingvolume.BoundingVolume()
		return boundingvolume.cacheVolume(
			self, volume, ((self, 'geometry'),(volume,None)),
		)

	def visible( self, frustum=None, matrix=None, occlusion=0, mode=None ):
		"""Check whether this renderable node intersects frustum

		frustum -- the bounding volume frustum with a planes
			attribute which defines the plane equations for
			each active clipping plane
		matrix -- the active OpenGL transformation matrix for
			this node, used to determine the transforms for
			the grouping-node's bounding volumes.  Is calculated
			from current OpenGL state if not provided.
		"""
		try:
			return self.boundingVolume(mode).visible( 
				frustum, matrix, occlusion=occlusion, mode=mode 
			)
		except Exception, err:
			fh = cStringIO.StringIO()
			tb = traceback.print_exc( file=fh )
			tb = fh.getvalue()
			fh.close()
			visitor_log.warn(
				"""Failure during Shape.visible check for %r:\n%s""",
				self,
				tb
			)
	
