"""node-path implementation for OpenGLContext
"""
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import numpy
from vrml.vrml97 import nodepath, nodetypes
from vrml.cache import CACHE
from OpenGLContext import quaternion
from OpenGL.GL import glMultMatrixf

class _NodePath( object ):
    """OpenGLContext-specific node-path class

    At the moment this only adds a single method,
    transform() which traverses the path, calling
    transform() for each Transforming node which
    has a transform method.
    """
    __slots__ = ()

    if TYPE_CHECKING:
        # What this mix-in needs of the path class beside it, declared for a
        # checker and nothing else: ``nodepath.NodePath`` is what supplies them.
        def __iter__(self) -> Iterator[Any]: ...
        def transformMatrix(self, translate: bool = True, scale: bool = True,
                            rotate: bool = True, matrixHolder: bool = False,
                            inverse: bool = False) -> Any: ...

    def transform( self, mode: Any = None, translate: int = 1,
                   scale: int = 1, rotate: int = 1 ) -> None:
        """For each Transforming node, do OpenGL transform

        Does _not_ push-pop matrices, so do that before
        if you want to save your current matrix.  This method
        is useful primarily for storing paths to, for instance,
        bindable nodes, where you want to be able to rapidly
        transform down to the node, without needing a full
        traversal of the scenegraph.
        """
        matrix = self.transformMatrix(
            translate=bool(translate), scale=bool(scale), rotate=bool(rotate)
        )
        glMultMatrixf( 
            matrix
        )
    def quaternion( self ) -> quaternion.Quaternion:
        """The rotation the path's transforms turn by, with their scale taken out

        Read from :meth:`transformMatrix`, so every transforming node on the
        path counts (Transform, MatrixTransform, a turned Billboard); the
        nearest rotation to a scaled or sheared matrix is used.
        """
        matrix = numpy.asarray( self.transformMatrix(), dtype='d' )[:3, :3]
        left, _scale, right = numpy.linalg.svd( matrix )
        rotation = left @ right
        if numpy.linalg.det( rotation ) < 0:
            rotation = -rotation
        return quaternion.fromMatrix( rotation )
        

class NodePath( _NodePath, nodepath.NodePath ):
    pass
class WeakNodePath( _NodePath, nodepath.WeakNodePath ):
    pass
