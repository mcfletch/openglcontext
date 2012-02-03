"""Holder for metadata regarding a polygon"""
from OpenGLContext.scenegraph import polygontessellator
from OpenGLContext import vectorutilities, utilities
from OpenGLContext.arrays import *
import logging
log = logging.getLogger( __name__ )

def mag( x, y, z ):
    """Get the 3D magnitude of a 3-coordinate vector"""
    return sqrt(x*x + y*y + z*z)

class Polygon( list ):
    """Holder for metadata regarding a particular polygon

    Often during certain operations (such as tessellation)
    is useful to have an object for representing a polygon
    which binds together all the metadata regarding that
    polygon.

    The Polygon class is modeled as a simple list-of-vertices
    with a convenience method normalise to make the class
    easier to use when dealing with triangle-only systems
    such as the array geometry classes.
    """
    def __init__( self, polyIndex=-1, node=None, points=None, ccw=True ):
        """Initialize the polygon

        polyIndex -- more accurately "polygon ID", an opaque
            value used to identify the polygon.
        node -- optional reference to the scenegraph node from
            which we are derived, used primarily during error
            reporting to give feedback regarding which node has
            encountered the error.
        points -- list of vertices which make up the definition
            of the polygon.
        """
        super(Polygon, self).__init__( points or [] )
        self.polyIndex = polyIndex
        self.node = node
        self.normalised = None
        self.ccw = ccw
    def normalise( self, tessellate=None ):
        """Normalise this polygon to a set of triangle vertices

        tesselate -- callable which can accept a Polygon instance
            and return a list of vertices representing a
            tesselated polygon triangle-set.  (And only a triangle-
            set, no triangle-fans or triangle-strips).
        """
        if self.normalised is not None:
            return self.normalised
        if tessellate is None:
            tessellate = polygontessellator.PolygonTessellator().tessellate
        if (
            len(self) > 4 or
            (
                len(self) == 4 and
                utilities.coplanar( [v.point for v in self] )
            )
        ):
            ### we would like to cache this partial solution somewhere
            ## but at the moment I don't see how to do it usefully,
            ## given that there may be a different tessellation required
            ## if the vertex positions change
##			if not self.ccw:
##				self.reverse()
            self[:] = tessellate ( self )
        elif len(self) == 4:
            a,b,c,d = self
            self[:] = [a,b,c,a,c,d]
        elif len(self) < 3:
            log.info( repr(
                DegeneratePolygon(
                    self,
                    self.node,
                    """Less than 3 vertices specified in indices""",
                )
            ))
        ### doing a sanity check an excluding degenerate polygons exclusively...
        return self.checkVertices()
        
    def checkVertices( self ):
        """Check set of triangle vertices for possible degeneracy

        At the moment this checks for condition:

            * vertices are collinear

        Returns only the well formed triangles from the input
        triangle vertex set.  (Note that this is called by normalise,
        which explains the rather strange input and output).
        """
        result = []
        localVertices = self[:]
        set = {}
        while localVertices:
            # first check, are there any triangles with two points equal?
            currentVertices = localVertices[:3]
            del localVertices[:3]
            # okay, there are three distinct vertices.
            # now check to see if the three vertices are co-linear.
            # lengths will cancel out if collinear...
            if len(currentVertices) == 3:
                a,b,c = [asarray(x.point,'f') for x in currentVertices]
                if not vectorutilities.colinear( (a,b,c) ):
                    #that's it, I think, no other sanity checks?
                    result.extend( currentVertices )
                else:
                    log.info( repr(
                        DegeneratePolygon(
                            currentVertices,
                            self.node,
                            """Vertices are collinear""",
                        )
                    ))
            else:
                log.info( repr(
                    DegeneratePolygon(
                        currentVertices,
                        self.node,
                        """Fewer than 3 vertices""",
                    )
                ))
        self.normalised = result
        return result
    def __repr__(self,):
        """Produce code-like representation of the polygon"""
        return """%s([\n\t%s],\n\t%s)"""%(
            self.__class__.__name__,
            "\n\t".join(map(repr,self)),
            self.node,
        )

class DegeneratePolygon(object):
    """Class encapsulated a degenerate triangle definition

    At the moment this is not a particularly useful class,
    eventually it might be used for interactive debugging
    of the geometry (for instance highlighting the degenerate
    polygons with indexed line sets).

    Note: an index of -1 indicates a likely tesselation-
    generated vertex.
    """
    def __init__(
        self, 
        vertices,
        node=None,
        reason = "",
    ):
        """Initialize the DegeneratePolygon instance

        vertices -- sequence of vertices
        node -- optional pointer to the source node
        reason -- string description of the condition which
            makes this a degenerate polygon definition.
        """
        self.node = node
        self.reason = reason
        self.vertices = vertices
    def __repr__(self,):
        return """%s([\n\t%s],\n\t%s,\n\t%r)"""%(
            self.__class__.__name__,
            "\n\t".join(map(repr,self.vertices)),
            self.node,
            self.reason,
        )
