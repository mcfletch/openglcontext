"""VRML97 Level-of-Detail node"""
from vrml.vrml97 import basenodes, nodetypes

class LOD(basenodes.LOD):
    """Level-of-Detail node based on VRML 97 LOD
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#LOD
    """
    def renderedChildren( self, types= (nodetypes.Children, nodetypes.Rendering,) ):
        """Choose child from level that is at appropriate range"""
        # We don't have a pointer to the visitor, that's
        # a serious shortcoming of the rendervisitor approach :(
        
        # What we really want is a set of two paths from
        # this node to the root and from the root to the
        # current viewpoint position (which is currently
        # just stored in the viewplatform).
        
        # That's pretty heavy for such a minimally useful LOD
        # interface IMO.
        if self.level:
            return [ self.level[0] ]