"""Box node for use in geometry attribute of Shapes"""
from vrml import cache
from vrml.vrml97 import basenodes
from vrml import protofunctions

class Coordinate( basenodes.Coordinate ):
    """Coordinate, storage of a sharable SFVec3f of points
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Coordinate
    """
    def boundingVolume( self, mode ):
        """Create a bounding-volume object for this node"""
        from OpenGLContext.scenegraph import boundingvolume
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current
        else:
            return boundingvolume.volumeFromCoordinate(
                self,
            )