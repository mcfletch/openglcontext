"""Base loader module for OpenGLContext
"""
import logging 
log = logging.getLogger( __name__ )
import urllib

class BaseHandler( object ):
    """Base handler class providing common loading operations
    """
    filename_extensions = []
    def __call__( self, baseURL, filename, file, *args, **named ):
        """Load encoded scenegraph from the file

        baseURL -- the URL from which the file was loaded
        filename -- the local filename for the file
        file -- open read-only file handle

        Returns a scenegraph or None
        """
        data = self.getData( baseURL, filename, file )
        success, sg = self.parse( data, baseURL, filename, file, *args, **named )
        if success and sg:
            log.debug( "parse complete")
            return sg
        elif not success:
            log.warn( "parse of %s failed", baseURL)
            raise ValueError( """Parse failure for url %s""", baseURL)
        else:
            log.warn( "parse of %s returned NULL document")
            raise ValueError( """NULL results for url %s""", baseURL)
    def parse( self, data, baseURL, filename, file, *args, **named ):
        """Parse the loaded data (with the provided meta-information)"""
        raise NotImplemented( """%s does not implement parse method""", self.__class__.__name__ )
    def getData( self, baseURL, filename, file ):
        """Retrieve data to be parsed
        
        Will handle gunzipping data which has .gz extension
        """
        # handle potential for a gzipped file...
        log.debug( "File handler file: %s", filename)
        # Okay, file is an open file
        # check the type to see if we need to gunzip
        if self.isGzip( file ):
            log.debug( "gunzip: %s", filename )
            file = self.gunzip( file )
        # Should check the file type,
        # just in case it's not really VRML, but that's
        # not really critical at the moment.
        
        # Get the data as in-memory string
        log.debug( "read: start")
        data = file.read()
        log.debug( "read: %s bytes", len(data))
        return data
    def isGzip( cls, file ):
        """Determine whether the data is a gzip stream"""
        previous = file.tell()
        try:
            file.seek(0)
            magic = file.read(5)
            if magic[:3] == '\037\213\010':
                return True
            else:
                return False
        finally:
            file.seek(previous)
    isGzip = classmethod( isGzip )
    def gunzip( cls, file ):
        """Get a gzip-aware file for the given file handle"""
        import gzip
        return gzip.GzipFile("","rb", 9, file)
    gunzip = classmethod( gunzip )
