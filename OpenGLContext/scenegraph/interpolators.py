"""Interpolator code for OpenGLContext"""

from typing import TYPE_CHECKING, Any, Optional

from vrml.vrml97 import basenodes
from OpenGLContext import quaternion


class Interpolator(object):
    """Mix-in class for Interpolators"""

    if TYPE_CHECKING:
        # What this mix-in needs of the node beside it, declared for a checker
        # and nothing else: all three are VRML97 fields of the interpolator
        # nodes, and a real declaration here would register a second copy.
        key: Any
        keyValue: Any
        value_changed: Any

    def on_set_fraction(self, value: float) -> Optional[Any]:
        """The value this fraction names, published and returned

        Answers None only when the node holds no keys to interpolate between.
        """
        if not len(self.key) or not len(self.keyValue):
            return None
        previous = None
        previousKey: Optional[float] = None
        for key, orient in zip(self.key, self.keyValue):
            if key > value:
                if previousKey is None:
                    # before the first key: the first value, held
                    self.value_changed = orient
                else:
                    segmentFraction = (value - previousKey) / float(key - previousKey)
                    self.value_changed = self.interpolate(
                        previous,
                        orient,
                        segmentFraction,
                    )
                return self.value_changed
            elif key == value:
                self.value_changed = orient
                return self.value_changed
            previous, previousKey = orient, key
        # past the last key: the last value, held
        self.value_changed = self.keyValue[-1]
        return self.value_changed

    def interpolate(self, previous: Any, next: Any, segmentFraction: float) -> Any:
        """Interpolate between first and second by given fragment"""
        return (previous * (1 - segmentFraction)) + (next * segmentFraction)


class SetInterpolator(Interpolator):
    """Mix-in class for interpolators generating arrays of values

    Each key names a whole run of ``keyValue`` entries rather than one, so the
    run length is ``len(keyValue) // len(key)``.
    """

    def on_set_fraction(self, value: float) -> Optional[Any]:
        """The set of values this fraction names, published and returned

        Answers None only when the node holds no keys to interpolate between.
        """
        if not len(self.key) or not len(self.keyValue):
            return None
        previousKey: Optional[float] = None
        scale = len(self.keyValue) // len(self.key)
        for index, key in enumerate(self.key):
            if key > value:
                if previousKey is None:
                    # before the first key: the first set, held
                    self.value_changed = self.keyValue[:scale]
                else:
                    segmentFraction = (value - previousKey) / float(key - previousKey)
                    self.value_changed = self.interpolate(
                        self.keyValue[(index - 1) * scale : index * scale],
                        self.keyValue[index * scale : (index + 1) * scale],
                        segmentFraction,
                    )
                return self.value_changed
            elif key == value:
                self.value_changed = self.keyValue[index * scale : (index + 1) * scale]
                return self.value_changed
            previousKey = key
        # past the last key: the last set, held
        self.value_changed = self.keyValue[-scale:]
        return self.value_changed


class OrientationInterpolator(Interpolator, basenodes.OrientationInterpolator):
    """OrientationInterpolator based on VRML 97 OrientationInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#OrientationInterpolator

    Takes fractional values and maps into an orientation
    "script" of sorts to produce simple rotational changes
    """

    def interpolate(self, previous: Any, next: Any, segmentFraction: float) -> Any:
        """Interpolate between first and second by given fragment"""
        previous = quaternion.fromXYZR(*previous)
        next = quaternion.fromXYZR(*next)
        new = previous.slerp(next, segmentFraction)
        return new.XYZR()


class ColorInterpolator(Interpolator, basenodes.ColorInterpolator):
    """ColorInterpolator based on VRML 97 ColorInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#ColorInterpolator
    """


class ScalarInterpolator(Interpolator, basenodes.ScalarInterpolator):
    """ScalarInterpolator based on VRML 97 ScalarInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#ScalarInterpolator
    """


class PositionInterpolator(Interpolator, basenodes.PositionInterpolator):
    """PositionInterpolator based on VRML 97 PositionInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PositionInterpolator
    """


class CoordinateInterpolator(SetInterpolator, basenodes.CoordinateInterpolator):
    """CoordinateInterpolator based on VRML 97 CoordinateInterpolator
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PositionInterpolator
    """


# Normal interpolation needs quaternions for each item...
# NormalInterpolator( SetInterpolator, basenodes.NormalInterpolator ):
