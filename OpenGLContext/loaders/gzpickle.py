"""GZipped pickle format"""
import gzip
try:
    raise ImportError
    import cPickle as pickle
except ImportError:
    import pickle
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

filename_extensions = ['.pkl', '.pkl.gz']

def dumps( object):
    """Return a zipped pickle of the object as a string"""
    fileobj = StringIO()
    try:
        dump( object, fileobj )
        fileobj.flush()
        value = fileobj.getvalue()
    finally:
        fileobj.close()
    return value
def dump( object, fileobj ):
    """Given a scenegraph and a filename or file object, dump to file"""
    if isinstance( fileobj, str ):
        file = gzip.GzipFile( filename=fileobj, mode = 'wb')
    else:
        file = gzip.GzipFile( mode = 'wb', fileobj = fileobj )
    try:
        # note use of _binary_ pickle format for speed/size
        pickle.dump(object, file, 1)
    finally:
        file.close()
    
def loads( data ):
    """Given a _gzipped_ pickle of the object, return the object"""
    fileobj = StringIO(data)
    try:
        value = load( fileobj )
    finally:
        fileobj.close()
    return value

def load( file ):
    """Give a file or filename, load as a gzpickle file"""
    if isinstance( file, str ):
        file = gzip.GzipFile( filename=file, mode = 'rb', )
    else:
        file = gzip.GzipFile( mode = 'rb', fileobj = file )
    try:
        value = pickle.load(file)
    finally:
        file.close()
    return value
    