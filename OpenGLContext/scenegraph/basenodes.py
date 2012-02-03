"""Convenience module for working with scenegraph nodes

These are the OpenGLContext implementations of the various
vrml.vrml97.basenodes nodes (and a few others) which are made
available for direct, centralized access.  Node classes are registered
via SetupTools/Package Resources plugin/entry point declarations 
in the setup.py script (or in the setup.py script of another package).

You can create a new Node-type by registering the class via setuptools

    entry_points = {
        'OpenGLContext.scenegraph.nodes': [
            'NodeName = full.path.to.the.Class',
        ],
    }

and installing the .egg.

XXX currently there's no way to override a built-in node, that could 
be provided by having e.g. a precedence declaration for the nodes,
but at the moment that looks too messy to bother with.
"""
__all__ = []
PROTOTYPES = {}
import logging 
log = logging.getLogger( __name__ )

def _load( ):
    """Load the registered node-types from package resource declarations"""
    from OpenGLContext import plugins
    entrypoints = plugins.Node.all()
    for entrypoint in entrypoints:
        name = entrypoint.name 
        try:
            classObject = entrypoint.load()
        except (ImportError,AttributeError), err:
            log.warn( """Unable to load node implementation for %s: %s""", name, err )
        else:
            globals()[ name ] = classObject
            PROTOTYPES[ name ] = classObject
            __all__.append( name )
            log.debug( """Loaded node implementation for %s: %s""", name, classObject )

_load()
del _load
