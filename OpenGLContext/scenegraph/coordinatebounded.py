"""Mix-in for geometry classes where coordinate==bounding volume"""
from typing import TYPE_CHECKING, Any

from OpenGLContext.scenegraph import boundingvolume


class CoordinateBounded( object ):
    """Mix-in for coordinate-holding geometry to support boundingvolumes

    Basically this is just a mix-in for use when constructing
    coordinate-based node-types, provides the boundingVolume
    method required by the Frustum-culling API.
    """

    if TYPE_CHECKING:
        # What this mix-in needs of the node it is mixed into, declared for a
        # checker and nothing else: ``coord`` is a VRML97 field of the geometry
        # nodes, and a real declaration here would register a second copy.
        coord: Any

    def boundingVolume( self, mode: Any ) -> boundingvolume.BoundingVolume:
        """Create a bounding-volume object for this node

        This is our coord's boundingVolume, with the
        addition that any dependent volume must be dependent
        on our coord field as well.
        """
        return boundingvolume.volumeFromCoordinate( self.coord )
