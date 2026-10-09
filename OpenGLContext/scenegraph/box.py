"""Box node for use in geometry attribute of Shapes"""
import numpy as np
from collections.abc import Iterator
from typing import Any
from vrml.vrml97 import basenodes

from OpenGLContext.scenegraph import meshdata
from OpenGLContext.scenegraph.meshgeometry import LevelledMesh


class Box( LevelledMesh, basenodes.Box ):
    """A box of `size` centred on its local origin, drawn as the mesh of its twelve triangles

    Each face has its own corners, normals and texture coordinates, laid out
    as X3D says (:func:`yieldVertices`); the mesh carries tangents for a
    normal map (:class:`~OpenGLContext.scenegraph.meshgeometry.LevelledMesh`).

    Reference:
        http://www.web3d.org/technicalinfo/specifications/vrml97/part1/nodesRef.html#Box
    """
    #: Draws with the pass's lit programs alone, so one draw can serve every
    #: view of a frame that sees it; see :mod:`OpenGLContext.multiview.strategy`.
    multiviewShared = True

    def levelArrays( self, level: int ) -> Any:
        """The box's twelve triangles, each face's corners its own vertices"""
        verts = np.asarray( list( yieldVertices( self.size ) ), dtype=np.float32 )
        return meshdata.arrays( verts[:, 5:8], verts[:, 2:5], verts[:, 0:2] )

    def instanceContentKey(self) -> tuple[Any, ...]:
        """Boxes of the same size share geometry, so they batch as instances."""
        return ('Box', tuple(round(float(v), 6) for v in self.size), bool(self.solid))

    def boundingVolume( self, mode: Any = None ) -> Any:
        """The box's own extent"""
        from OpenGLContext.scenegraph import boundingvolume
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                size = self.size,
            ),
            ( (self, 'size'), ),
        )

def yieldVertices(size: Any) -> Iterator[Any]:
    x,y,z = size 
    x,y,z = x/2.0,y/2.0,z/2.0
    normal = ( 0.0, 0.0, 1.0)
    yield (0.0, 0.0)+ normal + (-x,-y,z)
    yield (1.0, 0.0)+ normal + (x,-y,z)
    yield (1.0, 1.0)+ normal + (x,y,z)
    yield (0.0, 0.0)+ normal + (-x,-y,z)
    yield (1.0, 1.0)+ normal + (x,y,z)
    yield (0.0, 1.0)+ normal + (-x,y,z)

    normal = ( 0.0, 0.0,-1.0)
    yield (1.0, 0.0)+ normal + (-x,-y,-z)
    yield (1.0, 1.0)+ normal + (-x,y,-z)
    yield (0.0, 1.0)+ normal + (x,y,-z)
    yield (1.0, 0.0)+ normal + (-x,-y,-z)
    yield (0.0, 1.0)+ normal + (x,y,-z)
    yield (0.0, 0.0)+ normal + (x,-y,-z)

    normal = ( 0.0, 1.0, 0.0)
    yield (0.0, 1.0)+ normal + (-x,y,-z)
    yield (0.0, 0.0)+ normal + (-x,y,z)
    yield (1.0, 0.0)+ normal + (x,y,z)
    yield (0.0, 1.0)+ normal + (-x,y,-z)
    yield (1.0, 0.0)+ normal + (x,y,z)
    yield (1.0, 1.0)+ normal + (x,y,-z)

    # seen from below with +Z as the view up
    normal = ( 0.0,-1.0, 0.0)
    yield (0.0, 0.0)+ normal + (-x,-y,-z)
    yield (1.0, 0.0)+ normal + (x,-y,-z)
    yield (1.0, 1.0)+ normal + (x,-y,z)
    yield (0.0, 0.0)+ normal + (-x,-y,-z)
    yield (1.0, 1.0)+ normal + (x,-y,z)
    yield (0.0, 1.0)+ normal + (-x,-y,z)

    normal = ( 1.0, 0.0, 0.0)
    yield (1.0, 0.0)+ normal + (x,-y,-z)
    yield (1.0, 1.0)+ normal + (x,y,-z)
    yield (0.0, 1.0)+ normal + (x,y,z)
    yield (1.0, 0.0)+ normal + (x,-y,-z)
    yield (0.0, 1.0)+ normal + (x,y,z)
    yield (0.0, 0.0)+ normal + (x,-y,z)

    normal = (-1.0, 0.0, 0.0)
    yield (0.0, 0.0)+ normal + (-x,-y,-z)
    yield (1.0, 0.0)+ normal + (-x,-y,z)
    yield (1.0, 1.0)+ normal + (-x,y,z)
    yield (0.0, 0.0)+ normal + (-x,-y,-z)
    yield (1.0, 1.0)+ normal + (-x,y,z)
    yield (0.0, 1.0)+ normal + (-x,y,-z)
