"""node-path implementation for OpenGLContext
"""
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
    def transform( self, mode=None, translate=1, scale=1, rotate=1 ):
        """For each Transforming node, do OpenGL transform

        Does _not_ push-pop matrices, so do that before
        if you want to save your current matrix.  This method
        is useful primarily for storing paths to, for instance,
        bindable nodes, where you want to be able to rapidly
        transform down to the node, without needing a full
        traversal of the scenegraph.
        """
        matrix = self.transformMatrix( 
            translate=translate, scale=scale, rotate=rotate
        )
        glMultMatrixf( 
            matrix
        )
    def quaternion( self ):
        """Get summary quaternion for all rotations in stack"""
        nodes = [
            node
            for node in self
            if (
                isinstance(node, nodetypes.Transforming) and
                hasattr( node, "orientation")
            )
        ]
        q = quaternion.Quaternion()
        for node in nodes:
            q = q * quaternion.fromXYZR( *node.orientation )
        return q
        

class NodePath( _NodePath, nodepath.NodePath ):
    pass
class WeakNodePath( _NodePath, nodepath.WeakNodePath ):
    pass
