"""Interpolator code for OpenGLContext"""
from vrml.vrml97 import basenodes
from OpenGLContext import quaternion

class Interpolator( object ):
    """Mix-in class for Interpolators"""
    def on_set_fraction( self, value ):
        """Given a floating point value, produce a new value"""
        if not len(self.key) or not len(self.keyValue):
            return
        previous = None
        previousKey = None
        start,stop = -1,-1
        for index,(key,orient) in enumerate(zip( self.key, self.keyValue )):
            if key > value:
                if previous is None:
                    self.value_changed = orient
                    return
                else:
                    segmentFraction = (value-previousKey)/float(key-previousKey)
                    self.value_changed = self.interpolate(
                        previous, orient, segmentFraction,
                    )
                    return self.value_changed
            elif key == value:
                self.value_changed = orient
                return self.value_changed
            previous,previousKey = orient,key
        # no key was greater than value, return last value
        self.value_changed = self.keyValue[-1]
        return self.value_changed
    def interpolate( self, previous, next, segmentFraction ):
        """Interpolate between first and second by given fragment"""
        return (previous *(1-segmentFraction)) + (next * segmentFraction)
class SetInterpolator( Interpolator ):
    """Mix-in class for interpolators generating arrays of values"""
    def on_set_fraction( self, value ):
        """Given a floating point value, produce a new orientation"""
        if not len(self.key) or not len(self.keyValue):
            return
        previous = None
        previousKey = None
        start,stop = -1,-1
        scale = len(self.keyValue)//len(self.key)
        for index,key in enumerate(self.key):
            if key > value:
                if index == 0:
                    self.value_changed = self.keyValue[:scale]
                    return
                else:
                    segmentFraction = (value-previousKey)/float(key-previousKey)
                    self.value_changed = self.interpolate(
                        self.keyValue[(index-1)*scale:(index)*scale],
                        self.keyValue[(index)*scale:(index+1)*scale],
                        segmentFraction,
                    )
                    return
            elif key == value:
                self.value_changed = self.keyValue[index*scale:(index+1)*scale]
                return
            previousKey = key
        # no key was greater than value, return last value
        self.value_changed = self.keyValue[-scale:]
        return
    

class OrientationInterpolator( Interpolator, basenodes.OrientationInterpolator ):
    """OrientationInterpolator based on VRML 97 OrientationInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#OrientationInterpolator

    Takes fractional values and maps into an orientation
    "script" of sorts to produce simple rotational changes
    """
    def interpolate( self, previous, next, segmentFraction ):
        """Interpolate between first and second by given fragment"""
        previous = quaternion.fromXYZR( * previous )
        next = quaternion.fromXYZR( * next )
        new = previous.slerp(
            next,
            segmentFraction
        )
        return new.XYZR()
        
class ColorInterpolator( Interpolator, basenodes.ColorInterpolator ):
    """ColorInterpolator based on VRML 97 ColorInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#ColorInterpolator
    """

class ScalarInterpolator( Interpolator, basenodes.ScalarInterpolator ):
    """ScalarInterpolator based on VRML 97 ScalarInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#ScalarInterpolator
    """

class PositionInterpolator( Interpolator, basenodes.PositionInterpolator ):
    """PositionInterpolator based on VRML 97 PositionInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PositionInterpolator
    """

class CoordinateInterpolator( SetInterpolator, basenodes.CoordinateInterpolator ):
    """PositionInterpolator based on VRML 97 PositionInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PositionInterpolator
    """

# Normal interpolation needs quaternions for each item...
# NormalInterpolator( SetInterpolator, basenodes.NormalInterpolator ):