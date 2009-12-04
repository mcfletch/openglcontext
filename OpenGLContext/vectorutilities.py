"""Utilities for processing arrays of vectors"""
from OpenGLContext.arrays import *
import math

def _aformat( a ):
    return getattr( a, 'dtype', 'f')

def crossProduct( set1, set2):
    """Compute element-wise cross-product of two arrays of vectors.
    
    set1, set2 -- sequence objects with 1 or more
        3-item vector values.  If both sets are
        longer than 1 vector, they must be the same
        length.
    
    returns a double array with x elements,
    where x is the number of 3-element vectors
    in the longer set
    """
    set1 = asarray( set1, _aformat(set1))
    set1 = reshape( set1, (-1, 3))
    set2 = asarray( set2, _aformat(set2))
    set2 = reshape( set2, (-1, 3))
    return cross( set1, set2 )

def crossProduct4( set1, set2 ):
    """Cross-product of 3D vectors stored in 4D arrays

    Identical to crossProduct otherwise.
    """
    set1 = asarray( set1, _aformat(set1))
    set1 = reshape( set1, (-1, 4))
    set2 = asarray( set2, _aformat(set1))
    set2 = reshape( set2, (-1, 4))
    result = zeros( (len(set1),4), _aformat(set1))
    result[:,:3] = cross( set1[:,:3],set2[:,:3])
    result[:,3] = 1.0
    return result

def magnitude( vectors ):
    """Calculate the magnitudes of the given vectors
    
    vectors -- sequence object with 1 or more
        3-item vector values.
    
    returns a float array with x elements,
    where x is the number of 3-element vectors
    """
    vectors = asarray( vectors, _aformat(vectors))
    if not (len(shape(vectors))==2 and shape(vectors)[1] in (3,4)):
        vectors = reshape( vectors, (-1,3))
    result = sum(vectors*vectors,1 ) # index 1
    sqrt( result, result )
    return result
def normalise( vectors ):
    """Get normalised versions of the vectors.
    
    vectors -- sequence object with 1 or more
        3-item vector values.
    
    returns a float array with x 3-element vectors,
    where x is the number of 3-element vectors in "vectors"

    Will raise ZeroDivisionError if there are 0-magnitude
    vectors in the set.
    """
    vectors = asarray( vectors, _aformat(vectors))
    vectors = reshape( vectors, (-1,3)) # Numpy 23.7 and 64-bit machines fail here, upgrade to 23.8
    mags = reshape( magnitude( vectors ), (-1, 1))
    mags = where( mags, mags, 1.0)
    return divide_safe( vectors, mags)

def colinear( points ):
    """Given 3 points, determine if they are colinear

    Uses the definition which says that points are collinear
    iff the distance from the line for point c to line a-b
    is non-0 (that is, point c does not lie on a-b).

    returns None or the first 
    """
    if len(points) >= 3:
        a,b,c = points[:3]
        cp = crossProduct(
            (b-a),
            (a-c),
        )
        if magnitude( cp )[0] < 1e-6:
            return (a,b,c)
    return None

def orientToXYZR( a, b ):
    """Calculate axis/angle rotation transforming vec a -> vec b"""
    if allclose(a,b):
        return (0,1,0,0)
    an,bn = normalise( (a,b) )
    angle = arccos(dot(an,bn))
    x,y,z = crossProduct( a, b )[0]
    if allclose( (x,y,z), 0.0):
        y = 1.0
    return (x,y,z,angle)
