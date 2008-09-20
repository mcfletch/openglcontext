"""Simple node holding Frame-counting values"""
from vrml import node, field

class FrameCounter( node.Node ):
	"""Simple node holding Frame-counting values

	This node is used to hold information about the amount
	of time required to render frames for the context.
	"""
	PROTO = 'FrameCounter'
	count = field.newField( 'count', 'SFInt32', 1, 0)
	totalTime = field.newField( 'totalTime', 'SFFloat', 1, 0.0)
	lastTime = field.newField( 'lastTime', 'SFFloat', 1, 0.0)

	def addFrame( self, duration ):
		"""Add the duration of a single frame to the counter

		This method does *not* send field changed events, so
		should not trigger a refresh of the scene, which is
		important, as it will be called after *every* frame.
		"""
		self.__class__.count.fset( self, self.count + 1, notify=0)
		self.__class__.totalTime.fset( self, self.totalTime + duration, notify=0)
		self.__class__.lastTime.fset( self, duration, notify=0)
		return duration
	def summary( self ):
		"""Give a summary of framerates

		returns (count, average fps, last fps)
		"""
		if self.count:
			reallySmall = 0.00000000001
			return (
				self.count,
				round(float( self.count)/(self.totalTime or reallySmall), 4),
				round(1.0/(self.lastTime or reallySmall), 4),
			)
		return (0,0,0)
	