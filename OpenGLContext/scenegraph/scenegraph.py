"""Scenegraph node"""
from vrml.vrml97 import scenegraph, nodetypes
from vrml import field, node
from OpenGL.GL import *

class SceneGraph(scenegraph.SceneGraph):
    """SceneGraph node, the root of a scenegraph hierarchy

    See:
        vrml.vrml97.scenegraph.SceneGraph for
        implementation details
    """
    boundViewpoint = node.SFNode( 'boundViewpoint' )
    viewpointPaths = ()
    def renderedChildren( self, types= (nodetypes.Children, nodetypes.Rendering,) ):
        """List of all children that are instances of given types"""
        return [
            child for child in self.children
            if isinstance( child, types)
        ]
    