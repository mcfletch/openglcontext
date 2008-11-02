"""VRML97-style Transform node"""
from OpenGL.GL import *
from OpenGLContext.scenegraph import grouping, boundingvolume
from vrml.vrml97 import basenodes, transformmatrix

from OpenGLContext.arrays import array, allclose, any
from math import pi
RADTODEG = 180/pi
NULLSCALE = (1.0,1.0,1.0)

class Transform(grouping.Grouping, basenodes.Transform):
	"""Transform node based on VRML 97 Transform

	The Transform node provides a fairly robust implementation
	of encapsulated local coordinate setup.  You can set translation,
	rotation, scale, scaleOrientation and center and have the matrices
	properly setup and restored (even when you have exceeded the
	matrix stack depth).

	Reference:
		http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Transform
	"""
	def transform( self, mode=None, translate=1, scale=1, rotate=1 ):
		''' Perform the actual alteration of the current matrix '''
		if translate and any(self.translation):
			glTranslated(*self.translation)
		if (scale or rotate) and any(self.center):
			glTranslated(*self.center)
			centered = 1
		else:
			centered = 0
		rx,ry,rz,ra = self.rotation
		if rotate and ra:
			glRotated( ra * RADTODEG, rx,ry,rz)
		if self.__dict__.has_key('scale'):
			tupScale = tuple(self.scale)
			if tupScale == NULLSCALE:
				del self.scale
				scale = 0
		else:
			scale = 0
		if scale:
			sx,sy,sz,sa = self.scaleOrientation
			if sa:
				glRotated( sa * RADTODEG, sx,sy,sz)
			glScaled( *tupScale )
			if sa:
				# XXX this is wrong, x,y,z should be dotted by
				# the inverse of the scale to get the proper
				# axis of orientation.  It's a minor error,
				# and very rare (scaleOrientation is not used
				# very commonly), but it is definitely an error.
				glRotated( -sa * RADTODEG, sx,sy,sz)
		if centered:
			glTranslated( *(-self.center))
	def boundingVolume( self ):
		"""Calculate the bounding volume for this node

		The bounding volume for a grouping node is
		the union of it's children's nodes, and is
		dependent on the children of the node's
		bounding nodes, as well as the children field
		of the node.
		"""
		current = boundingvolume.getCachedVolume( self )
		if current is not None:
			return current
		# need to create a new volume and make it depend
		# on the appropriate fields...
		volumes = []
		dependencies = [
			(self,'children'),
			(self,'translation'),
			(self,'rotation'),
			(self,'scale'),
			(self,'scaleOrientation'),
			(self,'center'),
		]
		unbounded = 0
		for child in self.children:
			try:
				if hasattr(child, 'boundingVolume'):
					volume = child.boundingVolume()
					volumes.append( volume )
					dependencies.append( (volume, None) )
			except boundingvolume.UnboundedObject:
				unbounded = 1
		try:
			volume = boundingvolume.BoundingBox.union(
				volumes,
				self.localMatrix()
			)
		except boundingvolume.UnboundedObject:
			unbounded = 1
		if unbounded:
			volume = boundingvolume.UnboundedVolume()
		return boundingvolume.cacheVolume( self, volume, dependencies )
	
	def localMatrix( self ):
		"""Calculate the transform's matrix manually"""
		d = self.__dict__
		return transformmatrix.transformMatrix (
			translation = d.get( "translation"),
			rotation = d.get( "rotation"),
			scale = d.get( "scale"),
			scaleOrientation = d.get( "scaleOrientation"),
			center = d.get( "center"),
		)

