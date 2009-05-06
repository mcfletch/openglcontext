"""Quadratic geometry types (cone, sphere, cylinder, etc)"""
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from vrml import field, protofunctions, node
from vrml.vrml97 import basenodes, nodetypes
from OpenGLContext import displaylist
from vrml import cache
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.arrays import *
from OpenGL.arrays import vbo

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

class Sphere( basenodes.Sphere ):
	"""Sphere geometry rendered with GLU quadratic calls"""
	_unitSphere = None
	def render (
			self,
			visible = 1, # can skip normals and textures if not
			lit = 1, # can skip normals if not
			textured = 1, # can skip textureCoordinates if not
			transparent = 0,
			mode = None, # the renderpass object for which we compile
		):
		"""Render the geometry"""
		vbos = mode.cache.getData(self)
		if not vbos:
			vbos = self.compile( mode = mode )
		if vbos is None:
			return 1
		coords,indices,count = vbos
		glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
		glPushAttrib(GL_ALL_ATTRIB_BITS)
		try:
			coords.bind()
			glEnableClientState(GL_VERTEX_ARRAY)
			glVertexPointer( 3, GL_FLOAT,32,coords)
			if visible:
				if textured:
					glEnableClientState(GL_TEXTURE_COORD_ARRAY)
					glTexCoordPointer( 3, GL_FLOAT,32,coords+12)
				if lit:
					glEnableClientState(GL_NORMAL_ARRAY)
					glNormalPointer( GL_FLOAT,32,coords+20 )
			# TODO: sort for transparent geometry...
			indices.bind()
			# Can loop loading matrix and calling just this function 
			# for each sphere you want to render...
			# include both scale and position in the matrix...
			glDrawElements( 
				GL_TRIANGLES, count, GL_UNSIGNED_SHORT, indices
			)
		finally:
			glPopAttrib()
			glPopClientAttrib()
			coords.unbind()
			indices.unbind()
			
	def compile( self, mode=None ):
		"""Compile this sphere for use on mode"""
		if self._unitSphere is None:
			# create a unitsphere instance for all instances
			Sphere._unitSphere = self.sphere( pi/32 )
		print 'recompiling'
		coords,indices = self._unitSphere
		coords = copy( coords )
		coords[:,0:3] *= self.radius
		vbos = vbo.VBO(coords), vbo.VBO(indices,target = 'GL_ELEMENT_ARRAY_BUFFER' ), len(indices)
		holder = mode.cache.holder( self, vbos )
		holder.depend( self, 'radius' )
		return vbos
	
	@classmethod
	def sphere( cls, phi=pi/8.0, latAngle=pi, longAngle=(pi*2) ):
		"""Create arrays for rendering a unit-sphere
		
		phi -- angle between points on the sphere (stacks/slices)
		
		Note: creates 'H' type indices...
		"""
		latsteps = arange( 0,latAngle+0.000003, phi )
		longsteps = arange( 0,longAngle+0.000003, phi )
		return cls._partialSphere( latsteps,longsteps )

	@classmethod
	def _partialSphere( cls, latsteps, longsteps ):
		"""Create a partial-sphere data-set for latsteps and longsteps"""
		ystep = len(longsteps)
		zstep = len(latsteps)
		xstep = 1
		coords = zeros((zstep,ystep,8), 'f')
		coords[:,:,0] = sin(longsteps)
		coords[:,:,1] = cos(latsteps).reshape( (-1,1))
		coords[:,:,2] = cos(longsteps)
		coords[:,:,3] = longsteps/(2*pi)
		coords[:,:,4] = latsteps.reshape( (-1,1))/ pi
		
		# now scale by sin of y's 
		scale = sin(latsteps).reshape( (-1,1))
		coords[:,:,0] *= scale
		coords[:,:,2] *= scale
		coords[:,:,5:8] = coords[:,:,0:3] # normals
		
		indices = zeros( (zstep-1,ystep-1,6),dtype='H' )
		# all indices now render the first rectangle...
		indices[:] = (0,0+ystep,0+ystep+xstep, 0,0+ystep+xstep,0+xstep)
		xoffsets = arange(0,ystep-1,1,dtype='H').reshape( (-1,1))
		indices += xoffsets
		yoffsets = arange(0,zstep-1,1,dtype='H').reshape( (-1,1,1))
		indices += (yoffsets * ystep)
		
		# now optimize/simplify the data-set...
		new_indices = []
		
		for (i,iSet) in enumerate(indices ):
			angle = latsteps[i]
			nextAngle = latsteps[i+1]
			if allclose(angle%(pi*2),0):
				iSet = iSet.reshape( (-1,3))[::2]
			elif allclose(nextAngle%(pi),0):
				iSet = iSet.reshape( (-1,3))[1::2]
			else:
				iSet = iSet.reshape( (-1,3))
			new_indices.append( iSet )
		indices = concatenate( new_indices )
		return coords.reshape((-1,8)), indices.reshape((-1,))
	
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
