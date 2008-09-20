"""Log OpenGL commands

Uses the logging module (via debug.logs) if available,
with debug.logs.opengl_log being the particular target
log.

Usage example:

	from OpenGLContext.debug import loggl
	loggl.enable()
	# do something complicated here
	loggl.disable()

	# if you're going to do this a lot,
	# use the following instead of disable
	
	from OpenGLContext.debug import loggl, logs
	logs.opengl_log.setLevel( logs.WARN )

	# and

	logs.opengl_log.setLevel( logs.INFO )

	# which avoids wrapping and unwrapping
	# the OpenGL.GL functions
	

If you have the Python 2.3 logging package installed,
you can set up a non-default target for the "OpenGL" log.
"""
from OpenGL import GL
import sys
from OpenGLContext.debug.logs import opengl_log, INFO, WARN

class Wrapper( object ):
	"""Wrapper object for OpenGL callable objects

	Eventually it would be nice to have this wrapper
	include such things as looking up constants to give
	their symbolic names, rather than their values.
	"""
	def __init__( self, name, function ):
		"""Initialize the wrapper object

		name -- the name of the object to appear in output
		function -- the callable object
		"""
		self.name = name
		self.function = function
	def __call__( self, *arguments, **named ):
		"""Call the callable object, logging the command to opengl_log"""
		if __debug__:
			opengl_log.info(
				'%s(%s)',
				self.name,
				", ".join(
					[repr(argument)[:20] for argument in arguments] +
					['%s=%s'%(key,repr(value)[:20]) for key,value in named.items() ]
				),
			)
		return self.function(*arguments, **named )

## Do the actual substitution
## it might be nice to make this a function
## but in the end, why not just do it when importing
## it's what you want to 90 percent of the time
def enable():
	"""Enable logging

	Replaces the contents of OpenGL.GL with the wrapped versions,
	and then sets the opengl_log level to one which will allow
	the logging to occur.
	"""
	for key in dir(GL):
		obj = getattr( GL, key )
		if callable( obj ):
			obj = Wrapper( key, obj )
			setattr(GL, key, obj )
	opengl_log.setLevel( INFO )
def disable(level = WARN):
	"""Disable logging

	Returns contents of OpenGL.GL to previous value.  Doesn't
	currently reset the log-level, should do that some day.
	"""
	for key in dir(GL):
		obj = getattr( GL, key )
		if isinstance( obj, Wrapper ):
			setattr(GL, key, obj.function )
	opengl_log.setLevel( level )
	