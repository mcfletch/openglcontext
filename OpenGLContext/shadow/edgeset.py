"""Class encapsulating the set of edges within an IndexedFaceSet"""
from OpenGLContext.arrays import *
from OpenGL.GL import *
import weakref
from OpenGLContext import triangleutilities
from OpenGLContext.shadow import volume as shadowvolume
from vrml.vrml97 import nodetypes

class EdgeSet( object ):
    """Set of edges for calculating ShadowVolume

    Attributes:
        points -- pointer to triangle vertex array
        normals -- pointer to per-triangle normals
        singleEdges -- set of edges with only a single face
            attached, Nx2x3 set of edge-points
        singleVectors -- planar equations of faces where only
            a single face is attached to an edge
        singleIndices -- triangle indices for single-faced edges
        doubleEdges -- set of edges with only two faces
            attached, Nx2x3 set of edge-points
        doubleVectors -- planar equations of faces where two faces
            are attached to the edge
        doubleEdges -- triangle indices for double-faced edges
        planeEquations -- set of all planeEquations
        shadowvolumes -- cache of Light:ShadowVolume mappings
        
    """
    points = () # shared with IFS
    normals = () # shared with IFS
    # single-edges have problems, but for now I'll keep them...
    singleEdges = ()
    singleVectors = ()
    doubleEdges = ()
    doubleVectors = ()
    planeEquations = ()
    shadowVolumes = None # weakref(lightObject): ShadowVolume

    def __init__( self, points, normals=None, ccw = 1 ):
        """Initialize the EdgeSet

        points -- n*3 array of points, n%3 == 0, where each
            set of three points defines a single triangle in
            ccw winding
        normals -- optional array of per-triangle normals, will
            be calculated if necessary
        ccw -- boolean indicating whether counter-clock-wise
            winding is to be used (normal OpenGL/VRML winding)
            if false, then use clockwise winding
            (Note that this has never been tested, as I don't
            have any cw geometry around to test with, and haven't
            felt energetic enough to work around the standard
            tools to make any)
        """
        self.volumes = weakref.WeakKeyDictionary()
        self.ccw = ccw
        
        self.points = points
        self.normals = triangleutilities.normalPerFace( points, ccw=ccw )
        self.points_to_edges()

    def points_to_edges( self ):
        """Take an (x,y,z)*3 point array and calculate edge-connectivity information
        """
        pointSet = {}
        normals = self.normals
        points = self.points

        ### planeEquations stores the plane equations for testing
        ## whether a given triangle is facing towards or away from
        ## a light-source
        planeEquations = []
        
        for triangleIndex in range(0, int(len(points)/3)):
            pointIndex = triangleIndex*3
            a,b,c = map(tuple,points[pointIndex:pointIndex+3])
            # this compresses the code in the gamasutra article
            # considerably because we know that
            # index of a < index of b < index of c
            # note: doesn't check that triangles are actually on
            # both sides of the edge (could be on top of one another)
            for key in [ (a,b),(b,c),(c,a) ]:
                pointSet.setdefault(key, ([],[]))[0].append( triangleIndex )
            x1,y1,z1 = normals[triangleIndex]
            w1 = dot(-normals[triangleIndex], a)
            planeEquations.append( (x1,y1,z1,w1) )
                
        for triangleIndex in range(0, int(len(points)/3)):
            pointIndex = triangleIndex*3
            a,b,c = map(tuple,points[pointIndex:pointIndex+3])
            for key in [ (a,c),(c,b),(b,a)]: # only case where an edge can be in reverse order
                if pointSet.get( key ):
                    pointSet.get(key)[1].append( triangleIndex )
        # store plane equations
        self.planeEquations = array(planeEquations,'d')
        # now pre-calculate the triangle values...
        # need to seperate into a couple of sets,
        # those with single-triangles, those with
        # two triangles, and all the rest (which
        # XXX we don't know how to handle at the moment)
        singleEdges = [] # Nx2x3 set of edge-points
        singleVectors = [] # planar equations of faces
        singleIndices = []
        doubleEdges = [] # Nx2x3 set of edge-points
        doubleVectors = [] # planar equations of faces
        doubleIndices = []
        # XXX just ignore the longer sets for now
        for key,(first,second) in pointSet.iteritems():
            if len(first) == 1 and len(second) == 1:
                if first[0] == second[0]:
                    continue
                first,second = first[0],second[0]
                
                doubleEdges.append( key )
                doubleVectors.append(
                    (planeEquations[first],planeEquations[second])
                )
                doubleIndices.append( (first,second) )
                    
            elif len(first) == 1 and len(second) == 0:
                # edge belongs solely to first triangle
                first = first[0]
                a,b = key
                singleEdges.append( (b,a) )
                singleVectors.append( planeEquations[first] )
                singleIndices.append( first )
                
            elif len(second) == 1 and len(first) == 0:
                # edge belongs solely to second triangle
                first = second[0]
                singleVectors.append( planeEquations[first] )
                singleIndices.append( first )
            else:
                print """Un-shadow-able edge encountered in edge-set"""
        self.singleVectors = array(singleVectors, 'd')
        self.singleEdges = singleEdges
        self.singleIndices = singleIndices
        
        self.doubleVectors = array(doubleVectors, 'd')
        self.doubleEdges = doubleEdges
        self.doubleIndices = doubleIndices

    def volume( self, lightPath, currentPath, cache=1 ):
        """Build/get a shadow volume for this edge-set and this light
        """
        # XXX doesn't use the light's localised location,
        # so will get messed up by any transform in the hierarchy :(
        light = lightPath[-1]
        vector = self.calculateLightVector( lightPath, currentPath )

        current = self.volumes.get( light )
        if current is not None:
            # potentially already available...
            position, volume = current
            if position == vector:
                return volume
        # okay, either the light has changed position or
        # we have never seen this before...
        volume = shadowvolume.Volume( self, vector )
        self.volumes[ light ] = (vector, volume)
        return volume
    def calculateLightVector( self, lightPath, currentPath ):
        """Get the source vector for the given light path

        Projects the light position into the local
        coordinate space of the currentPath and then
        sets up the w component to reflect the
        light-type
            0.0, for directional lights
            1.0, for positional lights
        """
        # Get the location/direction as a 4-element list with
        # 1.0 as the w-component
        light = lightPath[-1]
        assert isinstance( light, nodetypes.Light ), """edgeset got a non-light for volume calculation"""
        if hasattr( light, 'location' ):
            location = list(light.location)
            w = 1.0
        else:
            location = list(-light.direction)
            w = 0.0
        location.append( 1.0 )

        # project the position/direction of the light along
        # lightPath from local to global coordinates
        # then along currentPath from global to local
        # (the opposite of normal projection)
        toWorld = lightPath.transformMatrix()
        fromWorld = currentPath.itransformMatrix()
        location = dot(dot( location, toWorld ), fromWorld)

        # now make the w component reflect the light-type
        location[-1] = w
        return tuple(location)


def test():
    points = [
        (0,0,0),(1,0,0),(1,1,0),
        (0,0,0), (1,1,0),(0,1,0),
        (1,0,0), (0,1,-1),(1,1,0),
    ]
    set = EdgeSet( points )
    from OpenGLContext.scenegraph import light
    value1 = set.volume(
##		light.DirectionalLight(location=(0,0,10))
        light.PointLight(location=(0,0,10))
    )
    return value1.edges

def test2():
    from OpenGLContext.scenegraph.basenodes import IndexedFaceSet, Coordinate, PointLight
    node = IndexedFaceSet(
        coordIndex = [ 0,2,3,-1,3,1,0,-1,4,5,7,-1,7,6,4,-1,0,1,5,-1,5,4,0,-1,1,3,7,-1,7,5,1,-1,3,2,6,-1,6,7,3,-1,2,0,4,-1,4,6,2,-1 ],
        coord = Coordinate (
            point = [-0.3,0.0,0.3, 0.3,0.0,0.3, -0.3,0.0,-0.3, 0.3,0.0,-0.3, -0.3,4.9,0.3, 0.3,4.9,0.3, -0.3,4.9,-0.3, 0.3,4.9,-0.3],
        )
    )
    ag = node.arrayGeometry()
    set = EdgeSet( ag.vertices)
    set.volume(PointLight(location=(0,0,10)))

from OpenGLContext.scenegraph.basenodes import *
def test3():
    node = IndexedFaceSet (
        coordIndex = [ 0,1,2,-1,0,2,3,-1,0,3,4,-1,0,4,1,-1,1,5,2,-1,2,5,3,-1,3,5,4,-1,4,5,1,-1 ],
        coord = Coordinate (
            point = [0.0,1.0,0.0, -0.5,0.0,0.5, 0.5,0.0,0.5, 0.5,0.0,-0.5, -0.5,0.0,-0.5, 0.0,0.0,0.0],
        ),
    )
    ag = node.arrayGeometry()
    set = EdgeSet( ag.vertices )
    vol = set.volume(PointLight(location=(0,10,0)))
    print 'volume', vol.edges
##	import pdb
##	pdb.set_trace()
    
    
if __name__ == "__main__":
    print test3()