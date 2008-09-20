"""VRML97 Switch node"""
from vrml.vrml97 import basenodes, nodetypes
from OpenGLContext.scenegraph import boundingvolume

class Switch(basenodes.Switch):
	"""Switch node based on VRML 97 Switch
	Reference:
		http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Switch
	"""
	def renderedChildren( self, types= (nodetypes.Children, nodetypes.Rendering,) ):
		"""Children is not the source, choice is"""
		if self.whichChoice < 0 or self.whichChoice >= len(self.choice):
			return []
		else:
			node = self.choice[self.whichChoice]
			if isinstance( node, types):
				return [node]
			return []
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
		dependencies = [(self,'choice'),(self,'whichChoice')]
		unbounded = 0
		for child in self.renderedChildren():
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
	
