"""Quadratic geometry types (cone, sphere, cylinder, etc)"""
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from vrml import field, protofunctions, node
from vrml.vrml97 import basenodes, nodetypes
from OpenGLContext import displaylist
from vrml import cache
from OpenGLContext.scenegraph import boundingvolume

class Quadric( nodetypes.Geometry, node.Node ):
	"""Base-class for the various quadratic-type geometry classes"""
	def render (
			self,
			visible = 1, # can skip normals and textures if not
			lit = 1, # can skip normals if not
			textured = 1, # can skip textureCoordinates if not
			transparent = 0,
			mode = None, # the renderpass object for which we compile
		):
		"""Render the geometry"""
		dl = mode.cache.getData(self)
		if not dl:
			dl = self.compile(mode=mode)
		if dl is None:
			return 1
		# okay, is now a (cached) display list object
		dl()
	def compile( self, mode=None ):
		"""Compile a display-list for this geometry"""
		dl = displaylist.DisplayList()
		dl.start()
		try:
			quadratic = gluNewQuadric()
			try:
				self.parameters( quadratic )
				self.generate( quadratic )
				holder = mode.cache.holder(self, dl)
				for field in protofunctions.getFields( self ):
					# change to any field requires a recompile
					holder.depend( self, field )
				return dl
			finally:
				gluDeleteQuadric( quadratic )
		finally:
			dl.end()
	def parameters( self, quadratic ):
		"""Setup quadratic rendering parameters"""
		gluQuadricNormals(quadratic, GLU_SMOOTH)
		gluQuadricTexture(quadratic, GL_TRUE)
	def generate( self, quadratic ):
		"""Do the actual per-node generation of the geometry"""
		
	slices = field.newField( ' slices', 'SFInt32', 1, 12 )
	stacks = field.newField( ' stacks', 'SFInt32', 1, 12 )

class Sphere( basenodes.Sphere, Quadric):
	"""Sphere geometry rendered with GLU quadratic calls"""
	def generate( self, quadratic ):
		"""Do the actual per-node generation of the geometry"""
		gluSphere(
			quadratic,
			self.radius,
			self.slices,
			self.stacks,
		)
	def boundingVolume( self, mode=None ):
		"""Create a bounding-volume object for this node

		In this case we use the AABoundingBox, despite
		the presence of the bounding sphere implementation.
		This is just a preference issue, I'm using
		AABoundingBox everywhere else, and want the sphere
		to interoperate properly.
		"""
		current = boundingvolume.getCachedVolume( self )
		if current:
			return current
		return boundingvolume.cacheVolume(
			self,
			boundingvolume.AABoundingBox(
				size = (self.radius*2,self.radius*2,self.radius*2),
			),
			( (self, 'radius'), ),
		)
		
class Cone( basenodes.Cone, Quadric ):
	"""Cone geometry rendered with GLU quadratic calls"""
	stacks = field.newField( ' stacks', 'SFInt32', 1, 2 )
	loops = field.newField( ' loops', 'SFInt32', 1, 1 )
	def generate( self, quadratic ):
		"""Do the actual per-node generation of the geometry"""
		# missing bottom and boolean for bottom
		glPushMatrix()
		try:
			glTranslated( 0,-self.height/2.0, 0)
			glRotated( -90, 1,0,0)
			if self.side:
				gluCylinder(
					quadratic,
					self.bottomRadius,
					0.0,
					self.height,
					self.slices,
					self.stacks,
				)
			if self.bottom:
				# draw a disk facing downward from the current position
				glRotated( 180, 1,0,0)
				gluDisk(
					quadratic,
					0.0,
					self.bottomRadius,
					self.slices,
					self.loops,
				)
		finally:
			glPopMatrix()

	def boundingVolume( self, mode=None ):
		"""Create a bounding-volume object for this node

		In this case we use the AABoundingBox, despite
		the presence of the bounding sphere implementation.
		This is just a preference issue, I'm using
		AABoundingBox everywhere else, and want the sphere
		to interoperate properly.
		"""
		current = boundingvolume.getCachedVolume( self )
		if current:
			return current
		radius = self.bottomRadius
		return boundingvolume.cacheVolume(
			self,
			boundingvolume.AABoundingBox(
				size = (radius*2,self.height,radius*2),
			),
			( (self, 'bottomRadius'), (self,'height') ),
		)



class Cylinder( basenodes.Cylinder, Quadric ):
	"""Cylinder geometry rendered with GLU quadratic calls"""
	stacks = field.newField( ' stacks', 'SFInt32', 1, 2 )
	loops = field.newField( ' loops', 'SFInt32', 1, 1 )
	def generate( self, quadratic ):
		"""Do the actual per-node generation of the geometry"""
		glPushMatrix()
		try:
			glTranslated( 0,-self.height/2.0, 0)
			glRotated( -90, 1,0,0)
			if self.side:
				gluCylinder(
					quadratic,
					self.radius,
					self.radius,
					self.height,
					self.slices,
					self.stacks,
				)
			if self.top:
				glTranslated( 0, 0, self.height)
				gluDisk(
					quadratic,
					0.0,
					self.radius,
					self.slices,
					self.loops,
				)
				glTranslated( 0, 0, -self.height)
			if self.bottom:
				# draw a disk facing downward from the current position
				glRotated( 180, 1,0,0)
				gluDisk(
					quadratic,
					0.0,
					self.radius,
					self.slices,
					self.loops,
				)
		finally:
			glPopMatrix()
	def boundingVolume( self, mode=None ):
		"""Create a bounding-volume object for this node

		In this case we use the AABoundingBox, despite
		the presence of the bounding sphere implementation.
		This is just a preference issue, I'm using
		AABoundingBox everywhere else, and want the sphere
		to interoperate properly.
		"""
		current = boundingvolume.getCachedVolume( self )
		if current:
			return current
		radius = self.radius
		return boundingvolume.cacheVolume(
			self,
			boundingvolume.AABoundingBox(
				size = (radius*2,self.height,radius*2),
			),
			( (self, 'radius'), (self,'height') ),
		)
