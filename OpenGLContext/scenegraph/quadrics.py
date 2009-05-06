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
from OpenGLContext import vectorutilities
from OpenGL.arrays import vbo


def mesh_indices( zstep,ystep, xstep=1 ):
	# now the indices, same as all quadratics
	indices = zeros( (zstep-1,ystep-1,6),dtype='H' )
	# all indices now render the first rectangle...
	indices[:] = (0,0+ystep,0+ystep+xstep, 0,0+ystep+xstep,0+xstep)
	xoffsets = arange(0,ystep-1,1,dtype='H').reshape( (-1,1))
	indices += xoffsets
	yoffsets = arange(0,zstep-1,1,dtype='H').reshape( (-1,1,1))
	indices += (yoffsets * ystep)
	return indices

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
		raise NotImplementedError( """Haven't implemented %s compilation yet"""%(self.__class__.__name__,))
		

class Sphere( basenodes.Sphere, Quadric ):
	"""Sphere geometry rendered with GLU quadratic calls"""
	_unitSphere = None
	def compile( self, mode=None ):
		"""Compile this sphere for use on mode"""
		if self._unitSphere is None:
			# create a unitsphere instance for all instances
			Sphere._unitSphere = self.sphere( pi/32 )
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
		
		indices = mesh_indices( zstep, ystep )
		
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
	def compile( self, mode=None ):
		"""Compile this sphere for use on mode"""
		coords,indices = self.cone( self.height, self.bottomRadius, self.bottom, self.side )
		vbos = vbo.VBO(coords), vbo.VBO(indices,target = 'GL_ELEMENT_ARRAY_BUFFER' ), len(indices)
		holder = mode.cache.holder( self, vbos )
		holder.depend( self, 'bottomRadius' )
		holder.depend( self, 'height' )
		return vbos
	
	@classmethod
	def cone( 
		cls, height=2.0, radius=1.0, bottom=True, side=True,
		phi = pi/16, longAngle=(pi*2), top=False
	):
		"""Generate a VBO data-set to render a cone"""
		tip = (0,height/2.0,0)
		longsteps = arange( 0,longAngle+0.000003, phi )
		ystep = len(longsteps)
		zstep = 0
		if top:
			zstep += 2
		if side:
			zstep += 2
		if bottom:
			zstep += 2
		# need top-ring coords and 2 sets for 
		coords = zeros( (zstep,ystep,8), 'f')
		coords[:,:,0] = sin(longsteps) * radius
		coords[:,:,2] = cos(longsteps) * radius
		coords[:,:,3] = longsteps/(2*pi)
		def fill_disk( area ):
			"""fill in disk elements for given area"""
			# disk texture coordinates
			area[:,:,1] = -(height/2.0)
			# x and z are 0 at center
			area[1,:,0] = 0.0 
			area[1,:,2] = 0.0
			area[0,:,3] = sin( longsteps ) / 2.0 + .5
			area[0,:,4] = cos( longsteps ) / 2.0 + .5
			area[1,:,3:5] = .5
			# normal for the disk is all the same...
			area[:,:,5:8] = (0,-1,0)
		def fill_sides( area ):
			"""Fill in side-of-cylinder/cone components"""
			area[0,:,0:3] = (0,height/2.0,0)
			area[1:4,:,1] = -height/2.0
			area[0,:,4] = 0
			area[1,:,4] = 1.0
			# normals for the sides...
			area[0:2,:-1,5:8] = vectorutilities.normalise(
				vectorutilities.crossProduct( 
					area[0,:-1,0:3] - area[1,:-1,0:3],
					area[1,:-1,0:3] - area[1,1:,0:3]
				)
			)
			area[0:2,-1,5:8] = area[0:2,0,5:8]
			
		if side:
			fill_sides( coords[0:2] )
#			coords[0,:,0:3] = (0,height/2.0,0)
#			coords[1:4,:,1] = -height/2.0
#			coords[0,:,4] = 0
#			coords[1,:,4] = 1.0
#			# normals for the sides...
#			coords[0:2,:-1,5:8] = vectorutilities.normalise(
#				vectorutilities.crossProduct( 
#					coords[0,:-1,0:3] - coords[1,:-1,0:3],
#					coords[1,:-1,0:3] - coords[1,1:,0:3]
#				)
#			)
#			coords[0:2,-1,5:8] = coords[0:2,0,5:8]
			if bottom:
				# disk texture coordinates
				fill_disk( coords[2:4] )
		elif bottom:
			fill_disk( coords )
		# now the indices, same as all quadratics
		indices = mesh_indices( zstep, ystep )
		# compress out degenerate indices if present...
		new_indices = []
		if side:
			new_indices.append(
				indices[0].reshape((-1,3))[::2]
			)
			new_indices.append(
				indices[1].reshape((-1,3))
			)
			if bottom:
				new_indices.append(
					indices[2].reshape((-1,3))[1::2]
				)
		elif bottom:
			new_indices.append(
				indices[0].reshape((-1,3))[1::2]
			)
		indices = concatenate( new_indices )
		return coords.reshape( (-1,8)), indices.reshape( (-1,))
	
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

if __name__ == "__main__":
	c = Cone.cone()
	
