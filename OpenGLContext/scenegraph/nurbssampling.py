"""NURBS sampling nodes and the object-space-tessellation extension probe.

The VRML97 sampling nodes (:class:`NurbsToleranceSample`,
:class:`NurbsDomainDistanceSample`) map a sampling policy onto ``gluNurbsProperty``
calls, alongside :func:`initialise` / :func:`defaultSampling`. :mod:`nurbs`
re-exports these names, and the node registrations in
``OpenGLContext/__init__.py`` resolve them as ``nurbs.NurbsToleranceSample`` etc.
"""

import logging
from typing import Any

from vrml import node, field
from OpenGL.GLU import (
    GLU_DOMAIN_DISTANCE, GLU_OBJECT_PARAMETRIC_ERROR_EXT, GLU_OBJECT_PATH_LENGTH_EXT,
    GLU_PARAMETRIC_ERROR, GLU_PARAMETRIC_TOLERANCE, GLU_PATH_LENGTH, GLU_SAMPLING_METHOD,
    GLU_SAMPLING_TOLERANCE, GLU_U_STEP, GLU_V_STEP, gluNurbsProperty,
)
from OpenGL.GLU.EXT.object_space_tess import (
    gluInitObjectSpaceTessEXT,
)

log = logging.getLogger(__name__)

object_space_tess: Any = None


def initialise(context: Any = None) -> bool:
    """Initialise the NURBs extensions for a context"""
    global object_space_tess
    if object_space_tess is None:
        object_space_tess = gluInitObjectSpaceTessEXT()
    return bool(object_space_tess)


def defaultSampling() -> "NurbsToleranceSample":
    """Get a default sampling node"""
    if initialise():
        return NurbsToleranceSample(method="object", parametric=1, tolerance=5)
    else:
        return NurbsToleranceSample(method="screen", parametric=1, tolerance=5)


class NurbsSampling(node.Node):
    """A node-type specifying NURBs sampling method and parameters"""


class NurbsToleranceSample(NurbsSampling):
    """Path-length tolerance sampling

    Can be either screen-space or object space,
        method = "screen" -> tolerance in pixels
        method = "object" -> tolerance in object-space coordinates
    and either parametric or not
        if true, tolerance is parametric tolerance (e.g. 0.5)
    """

    method = field.newField("method", "SFString", 1, "screen")  # "screen"/"object"
    parametric = field.newField("parametric", "SFBool", 1, 0)
    tolerance = field.newField("tolerance", "SFFloat", 1, 50.0)

    def properties(self, nurbObject: Any) -> None:
        """Configure this sampling type"""
        ### get the appropriate sampling method...
        methods = (GLU_PATH_LENGTH, GLU_PARAMETRIC_ERROR)
        if self.method == "object":
            if not initialise():
                # do regular (non-extension) screen sampling...
                log.warning(
                    """%s declares 'object' sampling method, extension: object_space_tess not available -> ignoring""",
                    self,
                )
                self.method = "screen"
            else:
                methods = (GLU_OBJECT_PATH_LENGTH_EXT, GLU_OBJECT_PARAMETRIC_ERROR_EXT)
        elif self.method != "screen":
            log.warning(
                """%s declares %s sampling method, unknown type -> ignoring""",
                self,
                repr(self.method),
            )
        method = methods[self.parametric]

        gluNurbsProperty(nurbObject, GLU_SAMPLING_METHOD, method)
        if self.parametric:
            gluNurbsProperty(nurbObject, GLU_PARAMETRIC_TOLERANCE, self.tolerance)
        else:
            gluNurbsProperty(nurbObject, GLU_SAMPLING_TOLERANCE, self.tolerance)


class NurbsDomainDistanceSample(NurbsSampling):
    """Domain-distance parametric u and v coordinate sampling"""

    uStep = field.newField("uStep", "SFFloat", 1, 100.0)
    vStep = field.newField("vStep", "SFFloat", 1, 100.0)

    def properties(self, nurbObject: Any) -> None:
        """Configure this sampling type"""
        gluNurbsProperty(nurbObject, GLU_SAMPLING_METHOD, GLU_DOMAIN_DISTANCE)
        gluNurbsProperty(nurbObject, GLU_U_STEP, self.uStep)
        gluNurbsProperty(nurbObject, GLU_V_STEP, self.vStep)
