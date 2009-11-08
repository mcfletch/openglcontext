"""Functions for acquiring and instantiating available testing contexts

Testing modules can use these abstract functions to allow for
automatic adaptation to new interactive contexts.  You should
not use this module for real world applications, as it is
unlikely that nontrivial code will be completely stable across
all interactive context classes."""

import traceback, string, os
from OpenGLContext.debug.logs import context_log as log
from OpenGLContext import plugins, context

def getVRML( preference= None ):
    """Retrieve the preferred testing context:
    
    returns BaseContext (a class derived from context.Context)
    """
    return context.Context.getContextType( preference, plugins.VRMLContext )
def getInteractive( preference= None ):
    """Retrieve the preferred testing context:
    
    returns BaseContext (a class derived from context.Context)
    """
    return context.Context.getContextType( preference, plugins.InteractiveContext )
