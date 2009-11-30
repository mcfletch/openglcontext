"""Logging facilities for OpenGLContext

Requires Python 2.4+ traceback module as well as the 
Python 2.4+ logging module.
"""
import traceback
def getTraceback(error=None):
    """Get formatted exception"""
    try:
        return traceback.format_exc( 10 )
    except Exception, err:
        return str(error)

import logging
Log = logging.getLogger
logging.basicConfig( ) #level=logging.INFO )
#logging.getLogger( 'OpenGL.extensions' ).setLevel(
#	logging.INFO 
#)
#logging.getLogger( 'OpenGL.acceleratesupport' ).setLevel(
#	logging.DEBUG
#)
WARN = logging.WARN
ERROR = logging.ERROR
INFO = logging.INFO
DEBUG = logging.DEBUG
logging.Logger.getTraceback = staticmethod( getTraceback )

### Now the actual logs...
# TODO: eliminate this centralized declaration stuff...
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