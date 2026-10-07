"""Scenegraph node"""
from typing import Any

from vrml.vrml97 import scenegraph, nodetypes
from vrml import field, node
from vrml.x3d import scene as x3dscene
from OpenGL.GL import *

class SceneGraph(scenegraph.SceneGraph):
    """SceneGraph node, the root of a scenegraph hierarchy

    See:
        vrml.vrml97.scenegraph.SceneGraph for
        implementation details
    """
    boundViewpoint = node.SFNode( 'boundViewpoint' )
    viewpointPaths = ()
    def renderedChildren(
        self, types: Any = (nodetypes.Children, nodetypes.Rendering,)
    ) -> list[Any]:
        """List of all children that are instances of given types"""
        return [
            child for child in self.children
            if isinstance( child, types)
        ]
    


class X3DScene(SceneGraph, x3dscene.X3DScene):
    """An X3D document's scene, drawn as any `SceneGraph` is

    The document's profile, version, components, units, metadata and the
    problems reading it found are fields of `vrml.x3d.scene.X3DScene`.
    """
    PROTO = 'X3DScene'
