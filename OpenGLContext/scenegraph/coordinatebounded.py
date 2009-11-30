"""Mix-in for geometry classes where coordinate==bounding volume"""
from OpenGLContext.scenegraph import boundingvolume

class CoordinateBounded( object ):
    """Mix-in for coordinate-holding geometry to support boundingvolumes

    Basically this is just a mix-in for use when constructing
    coordinate-based node-types, provides the boundingVolume
    method required by the Frustum-culling API.
    """
    def boundingVolume( self, mode ):
        """Create a bounding-volume object for this node

        This is our coord's boundingVolume, with the
        addition that any dependent volume must be dependent
        on our coord field as well.
        """
        return boundingvolume.volumeFromCoordinate( self.coord )