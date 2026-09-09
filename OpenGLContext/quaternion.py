"""Simple module providing a quaternion class for manipulating rotations easily.

Note: all angles are assumed to be specified in radians.
Note: this is an entirely separate implementation from the PyOpenGL
    quaternion class.  This implementation assumes that Numeric python
    will be available, and provides only those methods and helpers
    commonly needed for manipulating rotations.
"""
from OpenGLContext import arrays as ar
from OpenGLContext import utilities

# Named rather than starred, because which implementation answers matters here.
# This module used `from math import *` followed by `from ...arrays import *`,
# so the array versions won every name the two share -- and the guards below
# were written for the scalar ones. `math.acos` raises on an argument just
# outside its domain, which is what `XYZR` catches; the array one answers
# `nan`, so the guard never fired and `nan` came back out instead.
#
# The rule here: `ar` throughout for the arithmetic. The scalar versions are
# not interchangeable even on scalars -- `utilities.normalise` answers float32,
# and numpy keeps a float32 where a Python float is the other operand, so
# `x * math.sin(r)` rounds the quaternion to single precision where
# `x * ar.sin(r)` does not.

def fromXYZR( x,y,z, r ):
    """Create a new quaternion from a VRML-style rotation
    x,y,z are the axis of rotation
    r is the rotation in radians."""
    x,y,z = utilities.normalise( (x,y,z) )
    return Quaternion ( ar.array( [
        ar.cos(r/2.0), x*(ar.sin(r/2.0)), y*(ar.sin(r/2.0)), z*(ar.sin(r/2.0)),
    ]) )
def fromEuler( x=0,y=0,z=0 ):
    """Create a new quaternion from a 3-element euler-angle
    rotation about x, then y, then z
    """
    if x:
        base = fromXYZR( 1,0,0,x)
        if y:
            base = base * fromXYZR( 0,1,0,y)
        if z:
            base = base * fromXYZR( 0,0,1,z)
        return base
    elif y:
        base = fromXYZR( 0,1,0,y)
        if z:
            base = base * fromXYZR( 0,0,1,z)
        return base
    else:
        return fromXYZR( 0,0,1,z)

def fromMatrix( matrix ):
    """Create a new quaternion from a rotation matrix.

    The inverse of :meth:`Quaternion.matrix`, and in the same row-vector
    convention: a point is ``point @ matrix``.  A 3x3 or a 4x4 is accepted; a
    4x4's translation is ignored, since a rotation is all a quaternion holds.

    What it is for: a rotation that arrives as a matrix -- a node's composed
    world transform, a basis built out of two directions -- and has to be
    written into a VRML ``rotation`` field, which is axis-angle.  Going
    through the quaternion rather than reading an axis straight off the matrix
    is what keeps it stable at a half turn, where the axis terms vanish.
    """
    m = ar.asarray( matrix, 'd' )[:3,:3]
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        # The common case.  s is 4w, and w is furthest from zero here.
        s = ar.sqrt( trace + 1.0 ) * 2
        w, x, y, z = (s/4.0, (m[1][2]-m[2][1])/s,
                      (m[2][0]-m[0][2])/s, (m[0][1]-m[1][0])/s)
    else:
        # At a half turn w vanishes and dividing by it loses the axis, so the
        # largest diagonal term picks which of x, y and z to build from.
        largest = 0
        for index in (1,2):
            if m[index][index] > m[largest][largest]:
                largest = index
        other, third = (largest+1) % 3, (largest+2) % 3
        s = ar.sqrt( 1.0 + m[largest][largest]
                  - m[other][other] - m[third][third] ) * 2
        axis = [0.0,0.0,0.0]
        axis[largest] = s/4.0
        axis[other] = (m[largest][other] + m[other][largest])/s
        axis[third] = (m[largest][third] + m[third][largest])/s
        w = (m[other][third] - m[third][other])/s
        x, y, z = axis
    return Quaternion( ar.array( [w,x,y,z], 'd' ) )

class Quaternion(object):
    """Quaternion object implementing those methods required
    to be useful for OpenGL rendering (and not many others)"""
    __slots__ = ('internal','__weakref__')
    def __init__ (self, elements = (1,0,0,0) ):
        """The initializer is a four-element array,
        
        w, x,y,z -- all elements should be doubles/floats
        the default values are those for a unit multiplication
        quaternion.
        """
        elements = ar.asarray( elements, 'd')
        length = ar.sqrt( ar.sum( elements * elements))
        if length != 1:
            elements = elements/length
        self.internal = elements
    def __mul__( self, other ):
        """Multiply this quaternion by another quaternion,
        generating a new quaternion which is the combination of the
        rotations represented by the two source quaternions.

        Other is interpreted as taking place within the coordinate
        space defined by this quaternion.

        Alternately, if "other" is a matrix, return the dot-product
        of that matrix with our matrix (i.e. rotate the coordinate)
        """
        if hasattr( other, 'internal' ):
            w1,x1,y1,z1 = self.internal
            w2,x2,y2,z2 = other.internal
            
            w = w1*w2 - x1*x2 - y1*y2 - z1*z2
            x = w1*x2 + x1*w2 + y1*z2 - z1*y2
            y = w1*y2 + y1*w2 + z1*x2 - x1*z2
            z = w1*z2 + z1*w2 + x1*y2 - y1*x2
            return self.__class__( ar.array([w,x,y,z],'d'))
        else:
            return ar.dot( self.matrix (), other )
    def XYZR( self ):
        """Get a VRML-style axis plus rotation form of the rotation.
        Note that this is in radians, not degrees, and that the angle
        is the last, not the first item... (x,y,z,radians)
        """
        w,x,y,z = self.internal
        # Rounding leaves `w` a hair outside the arc cosine's domain -- 
        # 1.00000000002 for what should be no rotation at all -- and there the
        # array implementation answers `nan` rather than raising, so the
        # domain is clamped rather than an exception caught.
        aw = ar.acos( min( 1.0, max( -1.0, float(w) ) ) )
        scale = ar.sin(aw)
        if not scale:
            return (0,1,0,0)
        return (x / scale, y / scale, z / scale, 2 * aw )
    def inverse( self ):
        """Construct the inverse of this (unit) quaternion 
        
        Quaternion conjugate is (w,-x,-y,-z), inverse of a quaternion
        is conjugate / length**2 (unit quaternion means length == 1)
        """
        w,x,y,z = self.internal 
        return self.__class__( ar.array((w,-x,-y,-z),'d'))
    def matrix( self, dtype='f',inverse=False ):
        """Get a rotation matrix representing this rotation
        
        dtype -- specifies the result-type of the matrix, defaults 
            to 'f' in order to match real-world precision of matrix 
            operations in video cards
        inverse -- if True, calculate the inverse matrix for the 
            quaternion
        """
        w,x,y,z = self.internal
        if inverse:
            x,y,z = -x,-y,-z
        return ar.array([
            [ 1-2*y*y-2*z*z, 2*x*y+2*w*z, 2*x*z-2*w*y, 0],
            [ 2*x*y-2*w*z, 1-2*x*x-2*z*z, 2*y*z+2*w*x, 0],
            [ 2*x*z+2*w*y, 2*y*z-2*w*x, 1-2*x*x-2*y*y, 0],
            [ 0,0,0,1],
        ], dtype=dtype)
    def __getitem__( self, x ):
        return self.internal[x]
    def __len__( self ):
        return len( self.internal)
    def __repr__( self ):
        """Return a human-friendly representation of the quaternion

        Currently this representation is as an axis plus rotation (in radians)
        """
        return """<%s XYZR=%s>"""%( self.__class__.__name__, list(self.XYZR()))
    def delta( self, other ):
        """Return the angle in radians between this quaternion and another.

        Return value is a positive angle in the range 0-pi representing
        the minimum angle between the two quaternion rotations.
        
        From code by Halldor Fannar on the 3D game development algos list
        """
        # The dot product, which is what the next line wants. This read
        # `sum(self.internal + other.internal)` -- the sum of the *addition* --
        # so two rotations 0.4 radians apart gave 2.55, and the arc cosine of
        # that is nan.
        cosValue = float(ar.sum(self.internal * other.internal))
        # A rotation and its negation are the same rotation, so the nearer of
        # the two is the one to measure; and rounding can leave the value a
        # hair outside the arc cosine's domain.
        cosValue = min(1.0, abs(cosValue))
        # The angle between two rotations is twice the angle between the
        # quaternions that carry them.
        return 2.0 * ar.acos( cosValue )
    def slerp( self, other, fraction = 0, minimalStep= 0.0001):
        """Perform fraction of spherical linear interpolation from this quaternion to other quaternion

        Algo is from: http://www.gamasutra.com/features/19980703/quaternions_01.htm
        """
        fraction = float( fraction )
        cosValue = float(ar.sum(self.internal * other.internal))
        # if the cosValue is negative, use negative target and cos values?
        # not sure why, it's just done this way in the sample code
        if cosValue < 0.0:
            cosValue = -cosValue
            target = -other.internal
        else:
            # TODO: figure out why other.internal[:] returns a 0-dim array!
            target = other.internal[::]
        if (1.0- cosValue) > minimalStep:
            # regular spherical linear interpolation
            angle = ar.acos( cosValue )
            angleSin = ar.sin( angle )
            sourceScale = ar.sin( (1.0- fraction) * angle ) / angleSin
            targetScale = ar.sin( fraction * angle ) / angleSin
        else:
            sourceScale = 1.0-fraction
            targetScale = fraction
        return self.__class__( (sourceScale * self.internal)+(targetScale * target) )

