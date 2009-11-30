"""Low-level holder for vertex information"""
from OpenGLContext.arrays import array

class Vertex(object):
    """Holds a single vertex during operations
    which tend to mess up vertex indexing and so
    prefer to have atomic objects for manipulation."""
    __slots__ = (
        'point','color','normal',
        'textureCoordinate',
        'metaIndex','coordIndex',
        'indexKey',
    )
    def __init__ (
        self,
        point = (0,0,0),
        color = None,
        normal = None,
        textureCoordinate = None,
        metaIndex = -1,
        coordIndex = -1,
        indexKey = None,
    ):
        """Initialize the Vertex

        point -- three-dimensional coordinate
        color -- optional three-float color
        normal -- optional three-dimensional normalized vector
        textureCoordinate -- optional two-dimensional texture coordinate
        metaIndex -- optional integer index into the source
            index array (i.e. coordIndex[metaIndex], colorIndex[metaIndex],...
            is the index which produced the vertex.
        """
        self.point = array( point,'d')
        self.color = color
        self.normal = normal
        self.textureCoordinate = textureCoordinate
        self.metaIndex = int(metaIndex)
        self.coordIndex = int(coordIndex)
        self.indexKey = indexKey
    def copy( self, metaIndex = - 1 ):
        """Copy the vertex with a different metaIndex"""
        return self.__class__(
            self.point, self.color,
            self.normal, self.textureCoordinate,
            metaIndex,
        )
    def __repr__( self ):
        """Get a debugging-friendly representation of the vertex"""
        return """%s((%s),index=%s)"""% (
            self.__class__.__name__,
            ",".join(map(str,tuple(self.point))),
            self.metaIndex,
        )
