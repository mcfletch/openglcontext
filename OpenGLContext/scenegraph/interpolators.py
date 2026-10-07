"""The interpolator nodes the engine registers: pyvrml97's runtime classes

Each sends its value on ``value_changed`` for the ``set_fraction`` it is given
and also returns it from ``on_set_fraction``, which is how a caller driving
one directly (:mod:`OpenGLContext.move.smooth`) reads the value. The
arithmetic is :mod:`vrml.x3d.interpolation` (ISO/IEC 19775-1, 19.4):
positions, numbers and coordinates straight between keys, orientations along
the shorter arc, colours in HSV, normals along their great circles.

``Interpolator`` and ``SetInterpolator`` are the mix-ins for an interpolator of
one value per key and of a run of values per key, for a node of an
application's own.
"""

from vrml.x3d.runtime import (
    ColorInterpolator,
    CoordinateInterpolator,
    Linear as Interpolator,
    NormalInterpolator,
    OrientationInterpolator,
    PositionInterpolator,
    Runs as SetInterpolator,
    ScalarInterpolator,
)

__all__ = [
    'ColorInterpolator', 'CoordinateInterpolator', 'Interpolator', 'NormalInterpolator',
    'OrientationInterpolator', 'PositionInterpolator', 'ScalarInterpolator', 'SetInterpolator',
]
