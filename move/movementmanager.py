"""Interactions for navigating the context"""
from gettext import gettext as _
from OpenGLContext import quaternion
from OpenGLContext.debug.logs import movement_log

class MovementManager( object ):
	"""Base class for movement interaction controllers"""
	commands = [
		# User-name, key, function-name
		(_('Examine'), 'examine', 'startExamineMode' ),
	]
	commandBindings = dict(
		# key : { addEventHandler parameters } 
	)
	context = None
	def __init__( self, platform ):
		"""Initialize direct movement with the platform it controls"""
		self.platform = platform
	def bind( self, context ):
		"""Bind this navigation mechanism to the context"""
		self.context = context
		movement_log.info( "Binding %r movement manager", self )
		for (title,key,function) in self.commands:
			binding = self.commandBindings.get( key )
			if binding is not None:
				func = getattr( self, function, None )
				if func is not None:
					movement_log.info( 'Movement binding: %s, %s', func, binding )
					context.addEventHandler(function=func,**binding)
				else:
					movement_log.warn( 'No method %s registered as handler for %s on %s', 
						function, key, self.__class__.__name__,
					)
	def unbind( self, context ):
		"""Unbind this navigation mechanism from the context"""
		movement_log.info( "Unbinding %r movement manager", self )
		for (title,key,function) in self.commands:
			binding = self.commandBindings.get( key )
			if binding is not None:
				func = None
				context.addEventHandler(function=func,**binding)
		self.context = None
	def startExamineMode (self, event):
		"""(callback) Create an examine mode interaction manager

		This callback creates an instance of
		examinemanager.ExamineManager, which will manage
		the user interaction during an "examination" of
		the scene.

		XXX
			Currently the "center" determination is broken,
			so rotation tends to occur around random points.
			I haven't yet figured out why :(
		"""
		from OpenGLContext.move import examinemanager
		try:
			center = event.unproject()
		except ValueError:
			center = self.platform.quaternion * [0,0,-10,0] + self.platform.position
		examinemanager.ExamineManager(
			self.context, self.platform, center,event,
		)
