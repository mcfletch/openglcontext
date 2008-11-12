"""Common implementation for grouping-type nodes"""
from OpenGL.GL import *
from vrml.vrml97 import nodetypes
from vrml import node, field
from OpenGLContext.scenegraph import boundingvolume


class ChildrenSensitiveField( node.MFNode ):
	"""Field sub-class/mix-in for checking children for sensitivity"""
	fieldType = "MFNode"
	def checkSensitive( self, client, value ):
		"""Check value to see if there are any sensor children"""
		client.sensitive = 0
		for child in value:
			if isinstance( child, nodetypes.PointingSensor ):
				client.sensitive = 1
				break
		return value
	def fset( self, client, value, notify=1 ):
		"""On set, do regular set, then check for sensitivity"""
		value = super( ChildrenSensitiveField, self).fset( client, value, notify )
		return self.checkSensitive(client,value)
	def fdel( self, client, notify=1):
		"""On del, do regular del, then check for sensitivity"""
		value = super( ChildrenSensitiveField, self).fset( client, value, notify )
		client.sensitive = 0
		return value

class Grouping(object):
	"""Light-weight grouping object based on VRML 97 Group Node

	Attributes of note within Grouping objects:

		children -- list of renderable objects with
			ChildrenSensitiveField implementation that
			sets the parent to sensitive if there is
			a PointingSensor child

	Note that this is a Mix-in class for Node classes
	"""
	sensitive = field.newField( " sensitive", "SFBool", 0, 0)
	children = ChildrenSensitiveField( 'children', 1, [])
	def renderedChildren( self, types= (nodetypes.Children, nodetypes.Rendering,) ):
		"""List all children which are instances of given types"""
		for child in self.children:
			if isinstance( child, types):
				yield child
	def visible( self, frustum=None, matrix=None, occlusion=0, mode=None ):
		"""Check whether this grouping node intersects frustum

		frustum -- the bounding volume frustum with a planes
			attribute which defines the plane equations for
			each active clipping plane
		matrix -- the active OpenGL transformation matrix for
			this node, used to determine the transforms for
			the grouping-node's bounding volumes.  Is calculated
			from current OpenGL state if not provided.
		"""
		
		return self.boundingVolume().visible( frustum, matrix, occlusion=occlusion, mode=mode )

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
		dependencies = [(self,'children')]
		unbounded = 0
		for child in self.children:
			try:
				if hasattr(child, 'boundingVolume'):
					volume = child.boundingVolume()
					volumes.append( volume )
					dependencies.append( (volume, None) )
				else:
					unbounded = 1
					break
			except boundingvolume.UnboundedObject:
				unbounded = 1
		try:
			volume = boundingvolume.BoundingBox.union( volumes, None )
		except boundingvolume.UnboundedObject:
			unbounded = 1
		if unbounded:
			volume = boundingvolume.UnboundedVolume()
		return boundingvolume.cacheVolume( self, volume, dependencies )
	
