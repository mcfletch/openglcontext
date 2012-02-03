"""Load-manager for downloading multi-value URLs

The Singleton "Loader" should be used for most interactions.
"""
import urllib, os
from cStringIO import StringIO
import logging 
log = logging.getLogger( __name__ )

class _Loader( object ):
    """(Singleton) Manager for downloading resources

    Is a generic class which provides download services
    which follow VRML97 semantics (multiple-URL definitions,
    with chaining to the first successful URL).

    The loader will attempt to use a local cache of files
    to prevent multiple downloading.
    """
    def __init__(
        self,
    ):
        """Initialize the Loader"""
        self.cache = {}

    def __call__( self, url, baseURL=None ):
        """Load the given multi-value url and call callbacks

        url -- vrml97-style url (multi-value string)
        baseURL -- optional base url from which items in url will
            be resolved.  protofunctions.root(node).baseURI will
            give you the baseURL normally used for the given node.

        raises IOError on failure
        returns (successfulURL, filename, open_file, headers) on success

        headers will be None for local files
        """
        log.info( "Loading: %s, %s", url, baseURL )
        if isinstance( url, (str, unicode) ):
            url = [url]
        file = None
        for u in url:
            # get the "absolute" url
            if baseURL:
                u = urllib.basejoin(baseURL, u )
            resolvedURL, file, filename, headers = self.get( u )
            if file is not None and filename is not None:
                break
        if not file or not filename:
            raise IOError( """Unable to download url %s"""%url)
        return ( resolvedURL, os.path.abspath(filename), file, headers )
    def get( self, url ):
        """Retrieve the given single-value URL

        url -- single-value URL, which may be a local filename
            or any URL type supported by urllib

        returns (baseURL, file, filename, headers)
        """
        headers = None
        if url in self.cache:
            filename = self.cache.get( url )
            log.debug( "cached: %s %s", url, filename )
            try:
                file = open( filename, 'rb')
            except (IOError,TypeError,ValueError):
                pass
        try:
            log.debug( "load: %s", url )
            file = open( url, 'rb' )
            filename = url
            baseURL = urllib.pathname2url( filename )
        except (IOError,TypeError,ValueError), err:
            if url.startswith( 'res://' ):
                # virtual URL in our resources directories...
                module = url[6:]
                if '.' not in module:
                    # TODO: check for other bad values?
                    name = 'OpenGLContext.resources.%s'%(module,)
                    module = __import__(name, {}, {}, name.split('.'))
                    filename = module.source
                    file = StringIO( module.data )
                    baseURL = url 
                else:
                    raise ValueError( 'Invalid character in resource url: %s'%(url,))
            else:
                # try to download
                try:
                    log.debug( "download: %s", url )
                    filename, headers = self.download( url )
                    log.debug( "downloaded to: %s", filename )
                    file = open( filename, 'rb')
                    baseURL = url
                except (IOError, TypeError, ValueError), err:
                    return (None, None,None,None)
        self.cache[ url ] = filename
        self.cache[ baseURL ] = filename
        return baseURL, file, filename, headers
    def download( self, url ):
        """Download the given url to local disk, return local filename"""
        filename, headers = urllib.urlretrieve(
            url,
        )
        return filename, headers
    
    loadedHandlers = {}
    def loadHandlers( self ):
        """Load all registered handlers"""
        from OpenGLContext import plugins
        entrypoints = plugins.Loader.all()
        for entrypoint in entrypoints:
            name = entrypoint.name 
            try:
                creator = entrypoint.load()
            except ImportError, err:
                log.warn( """Unable to load loader implementation for %s: %s""", name, err )
            else:
                try:
                    loader = creator()
                except Exception, err:
                    log.warn( """Unable to initialize loader implementation for %s: %s""", name, err )
                else:
                    for extension in entrypoint.check:
                        self.loadedHandlers[ extension ] = loader 
                    log.info( """Loaded loader implementation for %s: %s""", name, loader )
        
    def findHandler( self, url ):
        """Find registered handler for the url's apparent suffix
        
        TODO: allow for content-type operations after downloading the URL
        """
        if not self.loadedHandlers:
            self.loadHandlers()
        for extension in self.loadedHandlers.keys():
            if url.endswith( extension ):
                return self.loadedHandlers[ extension ]
        return None
    def load( self, url, baseURL = None ):
        """Load the given URL as a scenegraph

        url -- the URL (or list of URLs) from which to load
        baseURL -- optional base URL from which to determine
            relative URL values
        """
        handler = self.findHandler( url )
        if not handler:
            raise ValueError( """We do not have a registered handler for url %r, registered handlers: %r"""%(
                url, Loader.loadedHandlers.keys(),
            ))
        result = self( url, baseURL=baseURL )
        if not result:
            return result
        # now parse/convert to scenegraph...
        return handler( *result )

    def loads( self, data, baseURL='resource.wrl' ):
        """Load given raw data as a scenegraph
        
        baseURL -- base URL from which to determine
            relative URL values
        """
        handler = self.findHandler( baseURL )
        if not handler:
            raise ValueError( """We do not have a registered handler for url %r, registered handlers: %r"""%(
                baseURL, Loader.loadedHandlers.keys(),
            ))
        return handler.parse( data, baseURL, filename='', file=None )[1]

Loader = _Loader()
