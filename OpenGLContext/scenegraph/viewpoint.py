"""VRML97 Viewpoint node"""
from vrml.vrml97 import basenodes, nodetypes
from OpenGLContext import quaternion
from OpenGLContext import arrays

class Viewpoint(basenodes.Viewpoint):
    """Viewpoint node based on VRML 97 Viewpoint
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Viewpoint

    The viewpoint node in VRML is kind of a mess to work with,
    so we don't try to support much of its functionality.
    Mostly we want to use it for configuring the
    viewplatform initially and to allow for switching between
    predefined viewpoints within a world.
    """
    def moveTo( cls, path, context ):
        """Given a node-path to a viewpoint, move context's platform there"""
        matrix = path.transformMatrix( )
        node = path[-1]
        platform = context.platform
        if not platform:
            platform = context.platform = context.getViewPlatform()
        if node.jump:
            position = list(node.position)+[1]
            newPosition = arrays.dot( position, matrix )
            newOrientation = (
                path.quaternion() *
                quaternion.fromXYZR( *node.orientation )
            ).XYZR()
            platform.setPosition( newPosition )
            platform.setOrientation( newOrientation )
        platform.setFrustum( node.fieldOfView )
    