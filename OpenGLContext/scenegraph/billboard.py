"""VRML97's and X3D's Billboard, drawn as a group

Its children are drawn where its parent places it: they are not turned toward
the viewer about ``axisOfRotation``.
"""
from typing import Any

from vrml import cache
from vrml.vrml97 import basenodes
from OpenGLContext.scenegraph import grouping

#: Where a Billboard keeps the matrices a path through it reads, in vrml's cache.
MATRICES_KEY = 'billboard-local'


class Billboard(grouping.Grouping, basenodes.Billboard):
    """Billboard node: a group, its children unturned

    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Billboard
    """
    def transform( self, mode: Any = None, translate: int = 1, scale: int = 1,
                   rotate: int = 1 ) -> None:
        pass

    def localMatrices( self, translate: bool = True, scale: bool = True,
                       rotate: bool = True ) -> Any:
        """The holder of this node's (forward, inverse) matrices: None, None,
        as its children are not moved"""
        holder = cache.CACHE.getHolder( self, key=MATRICES_KEY )
        if holder is None:
            holder = cache.CACHE.holder( self, (None, None), key=MATRICES_KEY )
        return holder
