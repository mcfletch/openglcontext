"""VRML97 loader module for OpenGLContext

This module implements VRML97-parser handler for the
loader module.  The parser is provided by the
vrml.vrml97 module.  Of particular interest to the
end-developer is the standardPrototype function, which
allows you to register prototypes as standard features
for your VRML97 files.

By default, the standard prototype namespace is the
union of:
    vrml.vrml97.basenodes and
    OpenGLContext.scenegraph.basenodes

with prototypes from the second replacing those in the
first.
"""
from vrml.vrml97 import basenamespaces, parser, linearise, nodetypes
from vrml import node, protofunctions
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.loaders import base
from vrml.vrml97 import parseprocessor
import urllib,threading
import logging 
log = logging.getLogger( __name__ )

STANDARD_PROTOTYPES = basenamespaces.basePrototypes.copy()

def standardPrototype( prototype, key ):
    """Make the given prototype available as a standard prototype

    What this means is that VRML97 files loaded
    with this module will be able to access the prototype
    without needing to declare a PROTO within the
    file.

    The name registered is the result of protofunctions.name
    for the prototype.
    """
    name = protofunctions.name( prototype )
    STANDARD_PROTOTYPES[name] = prototype
    if name != key:
        log.warn( "Standard prototype %r is known by the key %r instead of it's prototype name", name, key )
    return name

### Update from the basenodes dictionary of OpenGLContext
for key,value in basenodes.PROTOTYPES.items():
    try:
        name = standardPrototype( value, key )
    except TypeError:
        pass

_parser = parser.Parser( parser.grammar, "vrmlFile")

class VRML97Handler( base.BaseHandler ):
    """Handler for loading VRML97-encoded scenegraphs

    This is a load handler for the loader module which
    will be instantiated by the load or loads function
    in order to handle the result of downloading/opening
    a VRML97-encoded file.

    The prototypes argument is normally a pointer to
    the STANDARD_PROTOTYPES namespace, so that prototype
    registration during downloading will be available
    during parsing.
    """
    filename_extensions = ['.wrl', '.wrl.gz', '.wrz', '.vrml', '.vrml.gz']
    LOCK = threading.RLock()
    def __init__( self, prototypes ):
        """Initialise the file-handler

        prototypes -- prototype namespace provided by the
            vrml.protonamespace package
        """
        self.prototypes = prototypes
    def parse( self, data, baseURL, *args, **named ):
        """Parse the loaded data (with the provided meta-information)"""
        self.LOCK.acquire()
        try:
            success, results, next = _parser.parse(
                data,
                processor = parseprocessor.ParseProcessor(
                    basePrototypes = self.prototypes,
                    baseURI = baseURL,
                )
            )
            if success:
                sg = results[1]
            else:
                sg = None
            return success, sg
        finally:
            self.LOCK.release()
    def dumps( cls, node ):
        """Dump node's representation to a VRML97 string"""
        return linearise.Lineariser().linear( node )
    dumps = classmethod( dumps )

    def dump( cls, node, file ):
        """Dump node's representation to a VRML97-formatted file"""
        data = cls.dumps( node )
        if isinstance( file, str ):
            file = open( file, 'w')
        file.write( data )
        file.close()
        return data
    dump = classmethod( dump )


def defaultHandler():
    """Produce a default handler object
    
    This is registered in the setup.py as the entry point for this plug-in
    """
    
    return VRML97Handler( STANDARD_PROTOTYPES )
