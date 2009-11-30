"""Utility functions for processing triangle vertex arrays"""
from OpenGLContext.arrays import *
import math
from OpenGLContext.vectorutilities import *

def basisVectors( vertices, components = 3, ccw=1 ):
    """Calculate basis vectors for given triangle vertices
    
    vertices -- x*components array of vertex
        coordinates, with x a multiple of 3, that
        is, the array shape is (x,components). If
        shape(vertices) is length 2 and the second
        component is 3 or 4, we don't reshape,
        otherwise we reshape as appropriate
    components -- number of components in an
        individual coordinate, see note for
        vertices.
    ccw -- whether to use counter-clock-wise
        winding
    
    returns two x/3 arrays of vectors, (second
    minus first, third minus second), that is,
    there are two arrays of vectors, each of
    which is 1/3 of the length of the original
    vertices array.
    """
    vertices = asarray( vertices, 'f')
    if len(shape(vertices))==2 and shape(vertices)[1] in (3,4):
        # don't reshape...
        pass
    else:
        vertices = reshape( vertices, (-1,components))
    firsts = vertices[0::3]
    seconds = vertices[1::3]
    thirds = vertices[2::3]
    if ccw:
        return seconds-firsts, thirds-seconds
    else:
        # clockwise winding, 
        return thirds-firsts, seconds-thirds
        
def centers( vertices, vertexCount=3, components = 3  ):
    """Calculate polygon center for given polygon vertices

    vertices -- x*components array of vertex
        coordinates, with x a multiple of vertexCount
    vertexCount -- the number of vertices in a given polygon
    components -- the number of coordinates in a given vertex
    
    returns x-length array of center coordinates

    Note: if the vertices array is not an even multiple
    of vertexCount by components floats, you'll get a
    ValueError raised.
    """
    vertices = asarray( vertices, 'f')
    targetShape = (-1, vertexCount, components)
    vertices = reshape( vertices, targetShape)
    # the center is the average of the vertices
    # (as far as we are concerned)
    vertices = sum( vertices, 1 )
    # note that this is done for space savings,
    # this does an in-place division, rather than
    # creating a new array
    vertices = divide(vertices, vertexCount, vertices )
    return vertices

def normalPerFace( vertices, ccw=1 ):
    """Calculate triangle normals for given triangle vertices

    vertices -- x*3 array of vertex
        coordinates, with x a multiple of 3
    ccw -- whether to use counter-clock-wise
        winding

    returns array of normal vectors
    """
    a,b = basisVectors( vertices, 3, ccw=ccw  )
    return normalise( crossProduct(a,b))

if __name__ == "__main__":
    def test():
        data = array( [
            [0,0,0],[1,0,0],[0,1,0],
            [1,0,0],[0,0,0],[0,1,0],
        ],'f')
        print normalPerFace( data )
        print centers( data )
    test()