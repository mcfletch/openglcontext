"""Utility to create an "infinite perspective matrix"

This is a requirement for the "Robust Stencil Shadow" algorithm
so it's packaged here as a gluPerspective replacement
"""
from OpenGLContext.arrays import *

def pinfPerspective( fov, aspect, near, far=None ):
    """Generate a perspective matrix for far@infinity

    This is basically a replacement for
        gluPerspective( fov, aspect, near, far )

        fov -- field of view in degrees (for compatability)
        aspect -- width/height (float)
        near -- near clipping plan in units-distance (float)
        far -- ignored, compatability with gluPerspective,
            this is always taken as inifinity

    The code is taken directly from the Siggraph paper
    """
    result = zeros( (4,4),'d')
    # need the cotangent of the field-of-view
    cotFOV = 1/tan(fov)
    result[0,0] = cotFOV/aspect
    result[1,1] = cotFOV
    result[2,2:4] = -1
    result[3,2] = -2*near
    return result