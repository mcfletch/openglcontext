"""VRML97 Level-of-Detail node"""
from vrml.vrml97 import basenodes, nodetypes

class LOD(basenodes.LOD):
    """Level-of-Detail node based on VRML 97 LOD
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#LOD
    """
    def renderedChildren( self, types= (nodetypes.Children, nodetypes.Rendering,) ):
        """Return the level to render.

        Range-based selection would need the camera position relative to this
        node, which this call does not receive: it would take the path from the
        root to this node and the path to the current viewpoint (held on the
        view platform). Absent that, the highest-detail level is returned.
        """
        if self.level:
            return [ self.level[0] ]