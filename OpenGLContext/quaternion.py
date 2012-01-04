"""Simple module providing a quaternion class for manipulating rotations easily.

Note: all angles are assumed to be specified in radians.
Note: this is an entirely separate implementation from the PyOpenGL
    quaternion class.  This implementation assumes that Numeric python
    will be available, and provides only those methods and helpers
    commonly needed for manipulating rotations.
"""
from math import *
from OpenGLContext.arrays import *
from OpenGLContext import utilities

def fromXYZR( x,y,z, r ):
    """Create a new quaternion from a VRML-style rotation
    x,y,z are the axis of rotation
    r is the rotation in radians."""
    x,y,z = utilities.normalise( (x,y,z) )
    return Quaternion ( array( [
        cos(r/2.0), x*(sin(r/2.0)), y*(sin(r/2.0)), z*(sin(r/2.0)),
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

class Quaternion(object):
    """Quaternion object implementing those methods required
    to be useful for OpenGL rendering (and not many others)"""
    __slots__ = ('internal','__weakref__')
    def __init__ (self, elements = [1,0,0,0] ):
        """The initializer is a four-element array,
        
        w, x,y,z -- all elements should be doubles/floats
        the default values are those for a unit multiplication
        quaternion.
        """
        elements = asarray( elements, 'd')
        length = sqrt( sum( elements * elements))
        if length != 1:
##			print 'fixing quaternion length', repr(length)
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
            return self.__class__( array([w,x,y,z],'d'))
        else:
            return dot( self.matrix (), other )
    def XYZR( self ):
        """Get a VRML-style axis plus rotation form of the rotation.
        Note that this is in radians, not degrees, and that the angle
        is the last, not the first item... (x,y,z,radians)
        """
        w,x,y,z = self.internal
        try:
            aw = acos(w)
        except ValueError:
            # catches errors where w == 1.00000000002
            aw = 0
        scale = sin(aw)
        if not scale:
            return (0,1,0,0)
        return (x / scale, y / scale, z / scale, 2 * aw )
    def matrix( self, dtype='f' ):
        """Get a rotation matrix representing this rotation
        
        dtype -- specifies the result-type of the matrix, defaults 
            to 'f' in order to match real-world precision of matrix 
            operations in video cards
        """
        w,x,y,z = self.internal
        return array([
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
        #first get the dot-product of the two vectors
        cosValue = sum(self.internal + other.internal)
        # now get the positive angle in range 0-pi
        return acos( cosValue )
    def slerp( self, other, fraction = 0, minimalStep= 0.0001):
        """Perform fraction of spherical linear interpolation from this quaternion to other quaternion

        Algo is from: http://www.gamasutra.com/features/19980703/quaternions_01.htm
        """
        fraction = float( fraction )
        cosValue = float(sum(self.internal * other.internal))
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
            angle = acos( cosValue )
            angleSin = sin( angle )
            sourceScale = sin( (1.0- fraction) * angle ) / angleSin
            targetScale = sin( fraction * angle ) / angleSin
        else:
            sourceScale = 1.0-fraction
            targetScale = fraction
        try:
            return self.__class__( (sourceScale * self.internal)+(targetScale * target) )
        except ValueError,  err:
            print sourceScale
            print self.internal 
            print targetScale
            print target 
            raise


def test ():
    print 'fromEuler'
    print fromEuler( pi/2 ).XYZR()
    print fromEuler( y = pi/2 ).XYZR()
    print fromEuler( z = pi/2 ).XYZR()
    print fromEuler( y = pi/2, z = pi/2 ).matrix()
    rot = fromEuler( y = pi/2, z = pi/2 ).XYZR()
    print apply( fromXYZR, rot).matrix()
    print fromEuler( y = pi/2, z = pi/2 )
    first = fromXYZR( 0,1,0,0 )
    second = fromXYZR( 0,1,0,pi )
    for fraction in arange( 0.0, 1.0, .01 ):
        print first.slerp( second, fraction )

if __name__== "__main__":
    test ()
