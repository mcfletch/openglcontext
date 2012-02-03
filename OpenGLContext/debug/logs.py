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
logging.Logger.getTraceback = staticmethod( getTraceback )
