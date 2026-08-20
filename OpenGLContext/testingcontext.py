"""Functions for acquiring and instantiating available testing contexts

Testing modules can use these abstract functions to allow for
automatic adaptation to new interactive contexts.  You should
not use this module for real world applications, as it is
unlikely that nontrivial code will be completely stable across
all interactive context classes."""

import optparse
from OpenGLContext import plugins, context, contextdefinition

# Test-runner can specify the base-class explicitly...
CONFIGURED_BASE = None
REQUIRED_EXTENSION_MISSING = 3 # process return-code for a missing extension


def getVRML( preference= None ):
    """Retrieve the preferred VRML-parsing context class

    returns BaseContext (a class derived from context.Context)

    Raises RuntimeError where there is no such context to be had; see
    :func:`getInteractive`.
    """
    if CONFIGURED_BASE:
        return CONFIGURED_BASE
    return _required(
        context.Context.getContextType( preference, plugins.VRMLContext ),
        preference, plugins.VRMLContext,
    )
def getInteractive( preference= None ):
    """Retrieve the preferred interactive context class

    preference -- the name of a windowing backend, or None to use whichever
        the environment and the user's configuration choose

    returns BaseContext (a class derived from context.Context)

    Raises RuntimeError where the backend is not registered, or is registered
    but will not import because the toolkit it needs is not installed. What a
    caller does with this is subclass it, and a missing base class is reported
    by Python as a metaclass conflict several frames away from the cause,
    naming neither the backend nor the package to install.
    """
    if CONFIGURED_BASE:
        return CONFIGURED_BASE
    return _required(
        context.Context.getContextType( preference, plugins.InteractiveContext ),
        preference, plugins.InteractiveContext,
    )

def _required( found, preference, type ):
    """Return the context class, or say what was asked for and what there is

    The import error itself is logged by the plug-in as it fails, which is
    where the message naming the package to install comes from; this says which
    backend was being asked for when it happened.
    """
    if found is not None:
        return found
    registered = sorted( plugin.name for plugin in type.all() )
    raise RuntimeError(
        """No %s is available for %r: it is either not one of the registered """
        """backends (%s) or its toolkit is not installed -- see the import """
        """error logged above."""
        % ( type.__name__, preference, ', '.join( registered ) or 'none' )
    )
