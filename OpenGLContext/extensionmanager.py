"""Object managing OpenGL extension loading for a Context"""
from OpenGL.GL import glGetString, GL_EXTENSIONS
from OpenGL.GLU import gluGetString, GLU_EXTENSIONS
import string, traceback
import logging 
log = logging.getLogger( __name__ )

class ExtensionManager( object ):
    """Object managing OpenGL extension loading and initialisation

    There are a large number of OpenGL extensions available,
    and it is generally necessary to initialize the extension
    for each OpenGL context.  This class attempts to provide
    a generic interface for instantiating and querying for the
    extension's current status with regard to a particular
    Context.

    This object is normally accessed via ContextObject.extensions,
    which is set up by the setupExtensionManager method of the
    base Context class, which is called before the OnInit method.

    Attributes:
        modules -- mapping from "cleaned" module name to module
            object (that is, the actual python module representing
            the extension)
    """
    def __init__( self ):
        """Initialise the extension manager

        This implementation simply creates the modules attribute.
        """
        self.modules = {}
    def hasExtension( self, moduleName ):
        """Query whether an extension is currently loaded

        moduleName -- the "cleaned" module name being queried
        """
        return moduleName in self.modules and (
            not not self.modules.get( moduleName )
        )
    
    def initExtension( self, moduleName ):
        """Initialise an extension module for the context

        This must be called within a "setcurrent" environment
        to ensure that the owning context is the one that's
        initialised...

        moduleName -- the module name being queried, will be
            "cleaned" before processing.  Format should be:
                "GLU.EXT.object_space_tess"
                "GL.ARB.multitexture"
            that is, with OpenGL. prepended, represents the
            Python module for the extension implementation.

        If the extension has already been loaded, this just
        returns a pointer to the already existing module.
        """
        # check here to see if already loaded for context...
        log.debug( """initExtension %r""", moduleName )
        moduleName = cleanModuleName( moduleName )
        if moduleName in self.modules:
            log.debug( """already have extension %r initialised""", moduleName )
            return self.modules.get( moduleName )
        try:
            module = importFromString( moduleName )
        except ImportError, err:
            # record fact of failure XXX should use logs...
            log.warn( """Unable to load module for extension %r""", moduleName )
            traceback.print_exc()
            self.modules[ moduleName ] = None
            return None
        else:
            initMethod = getattr( module, initialiser( moduleName))
            if initMethod():
                # record success
                log.info( """Module %r loaded""", moduleName )
                self.modules[ moduleName ] = module
                return module
            else:
                # record failure
                log.info( """Module %r unavailable (initialisation failure)""", moduleName )
                self.modules[ moduleName ] = None
                return None
    # convenience queries...
    def listGL( self ):
        """Return list of OpenGL extension names"""
        return glGetString( GL_EXTENSIONS).split()
    def listGLU( self ):
        """Return list of GLU extension names

        XXX This is currently broken with PyOpenGL 2.0.1
        """
        return gluGetString( GLU_EXTENSIONS ).split()
    def listWGL( self ):
        """Return list of WGL extension names"""
        extensions_string = self.initExtension(
            "OpenGL.WGL.EXT.extensions_string",
        )
        if extensions_string:
            return extensions_string.wglGetExtensionsStringEXT().split()
        else:
            return []

def cleanModuleName( moduleName ):
    """Get a valid PyOpenGL module name for given string

    Needs to deal with '_' vs '.' creating a result that's
    OpenGL.Package.SubPackage.extension_name
    """
    if not moduleName.find('OpenGL') == 0:
        moduleName = 'OpenGL_'+ moduleName
    moduleName = moduleName.replace( '.','_').split('_')
    return ".".join(moduleName[:3]) + '.' + "_".join(moduleName[3:])
    

def importFromString( moduleName ):
    """Import a fully-specified extension-module name"""
    return __import__( moduleName, {},{}, moduleName.split('.'))
def initialiser( moduleName ):
    """Compute the initialiser function name from module name"""
    moduleName = moduleName.replace(".","_")
    parts = moduleName.split('_')[1:] # strip OpenGL prefix
    return "".join([
        parts[0].lower(),
        'Init'
    ] + [ x.title() for x in parts[2:]] + [parts[1]])



if __name__ == "__main__":
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGL import WGL

    class TestContext( BaseContext ):
        def OnInit( self ):
            e = self.extensions
            print e.listGL()
            print e.listGLU()
            print e.listWGL()
            module = self.extensions.initExtension( "WGL.ARB.pixel_format" )
            print module
            d = dir(module)
            d.sort()
            for name in d:
                print '%r,'%(name)
    TestContext.ContextMainLoop()
