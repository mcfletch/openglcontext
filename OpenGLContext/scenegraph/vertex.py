"""Low-level holder for vertex information"""
from typing import Any

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
        point: Any = (0,0,0),
        color: Any = None,
        normal: Any = None,
        textureCoordinate: Any = None,
        metaIndex: int = -1,
        coordIndex: int = -1,
        indexKey: Any = None,
    ) -> None:
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
    def copy( self, metaIndex: int = -1 ) -> "Vertex":
        """Copy the vertex with a different metaIndex"""
        return self.__class__(
            self.point, self.color,
            self.normal, self.textureCoordinate,
            metaIndex,
        )
    def __repr__( self ) -> str:
        """Get a debugging-friendly representation of the vertex"""
        return """%s((%s),index=%s)"""% (
            self.__class__.__name__,
            ",".join([str(x) for x in tuple(self.point)]),
            self.metaIndex,
        )
