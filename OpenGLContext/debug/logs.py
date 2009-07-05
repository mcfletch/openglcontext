"""Logging facilities for OpenGLContext

If the logging package (from Python 2.3) is available,
we use it for our logging needs, otherwise we use a
simplistic locally-defined class for logging.
"""
import traceback
try:
	from cStringIO import StringIO
except ImportError, err:
	from StringIO import StringIO
def getTraceback(error):
	"""Get formatted exception"""
	exception = str(error)
	file = StringIO()
	try:
		traceback.print_exc( limit=10, file = file )
		exception = file.getvalue()
	finally:
		file.close()
	return exception

try:
	import logging
	Log = logging.getLogger
	logging.basicConfig( ) #level=logging.INFO )
	logging.getLogger( 'OpenGL.extensions' ).setLevel(
		logging.INFO 
	)
	WARN = logging.WARN
	ERROR = logging.ERROR
	INFO = logging.INFO
	DEBUG = logging.DEBUG
	logging.Logger.getTraceback = staticmethod( getTraceback )
except ImportError:
	# does not have the logging package installed
	import sys
	DEBUG = 10
	INFO = 20
	WARN = 30
	ERROR = 40
	class Log( object ):
		"""Stand-in logging facility"""
		level = WARN
		def __init__( self, name ):
			self.name = name
		def debug(self, message, *arguments):
			if self.level <= DEBUG:
				sys.stderr.write( 'DEBUG:%s:%s\n'%(self.name, message%arguments))
		def warn( self, message, *arguments ):
			if self.level <= WARN:
				sys.stderr.write( 'WARN:%s:%s\n'%(self.name, message%arguments))
		def error( self, message, *arguments ):
			if self.level <= ERROR:
				sys.stderr.write( 'ERR :%s:%s\n'%(self.name, message%arguments))
		def info( self, message, *arguments ):
			if self.level <= INFO:
				sys.stderr.write( 'INFO:%s:%s\n'%(self.name, message%arguments))
		def setLevel( self, level ):
			self.level = level


	Log.getTraceback = staticmethod( getTraceback )

### Now the actual logs...
context_log = Log( "context" )
visitor_log = Log( "context.visitor")
content_log = Log( "context.content")
geometry_log = Log( "context.content.geometry")
texture_log = Log( "context.content.textures")
text_log = Log( "context.content.geometry.text")
bounding_log = Log( "context.content.bounding")
loader_log = Log( "context.loader")
event_log = Log( "context.events")
shadow_log = Log( "context.content.shadow")
extension_log = Log( "context.extensions")
movement_log = Log( "context.move")

opengl_log = Log( "OpenGL")

#movement_log.setLevel( DEBUG )
#text_log.setLevel(DEBUG)
#context_log.setLevel( DEBUG )
#visitor_log.setLevel( DEBUG )
#loader_log.setLevel( DEBUG )
#geometry_log.setLevel( DEBUG )
