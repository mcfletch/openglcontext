"""NURBS sampling nodes: how finely a surface is tessellated.

Each node answers :meth:`~NurbsSampling.steps` with a sampling *rate* for each
parametric direction -- intervals per unit of knot range -- which
:mod:`OpenGLContext.scenegraph.nurbstess` multiplies by the surface's own range
to get the lattice it evaluates. A rate rather than a count, so two surfaces
sampled at the same rate come out with triangles the same size whatever their
knots run over.

:mod:`nurbs` re-exports these names, and the node registrations in
``OpenGLContext/__init__.py`` resolve them as ``nurbs.NurbsToleranceSample``
etc.
"""

import logging
from typing import Any

from vrml import field, node

log = logging.getLogger(__name__)

#: A tolerance of 5 -- the default sampling node's -- is a rate of 30, matching
#: :data:`~OpenGLContext.scenegraph.nurbstess.DEFAULT_STEP`; a tighter tolerance
#: asks for proportionally more.
TOLERANCE_RATE = 150.0

#: The rates a tolerance may be turned into. A tolerance is a distance and a
#: rate is a count, so nothing relates them exactly; these bounds keep the
#: relation from running away at either end.
MIN_TOLERANCE_STEPS = 20.0
MAX_TOLERANCE_STEPS = 100.0

#: The methods :class:`NurbsToleranceSample` recognises.
METHODS = ('screen', 'object')


def defaultSampling() -> "NurbsToleranceSample":
    """The sampling a surface gets when its scene names none."""
    return NurbsToleranceSample(method="screen", parametric=1, tolerance=5)


class NurbsSampling(node.Node):
    """A node-type specifying NURBs sampling method and parameters"""

    def steps(self) -> tuple[float, float]:
        """Sampling rate along u and along v, in intervals per unit of knot range."""
        raise NotImplementedError(
            '%s does not say how finely to sample' % (self.__class__.__name__,)
        )


class NurbsToleranceSample(NurbsSampling):
    """Sampling to a tolerance rather than to a step count

    Can be either screen-space or object space,
        method = "screen" -> tolerance in pixels
        method = "object" -> tolerance in object-space coordinates
    and either parametric or not
        if true, tolerance is parametric tolerance (e.g. 0.5)

    The tolerance sets a sampling rate: :data:`TOLERANCE_RATE` divided by it,
    held between :data:`MIN_TOLERANCE_STEPS` and :data:`MAX_TOLERANCE_STEPS`.
    A tolerance is a distance on a surface nobody has drawn yet, so a tighter
    one asks for a finer mesh without promising a deviation; where a scene wants
    a mesh of a stated size, :class:`NurbsDomainDistanceSample` states it.
    """

    method = field.newField("method", "SFString", 1, "screen")  # "screen"/"object"
    parametric = field.newField("parametric", "SFBool", 1, 0)
    tolerance = field.newField("tolerance", "SFFloat", 1, 50.0)

    def steps(self) -> tuple[float, float]:
        """The rate this tolerance asks for, the same in both directions."""
        if self.method not in METHODS:
            log.warning(
                """%s declares %s sampling method, unknown type -> ignoring""",
                self,
                repr(self.method),
            )
            self.method = "screen"
        rate = TOLERANCE_RATE / max(1.0, float(self.tolerance))
        rate = min(MAX_TOLERANCE_STEPS, max(MIN_TOLERANCE_STEPS, rate))
        return rate, rate


class NurbsDomainDistanceSample(NurbsSampling):
    """Domain-distance parametric u and v coordinate sampling

    ``uStep`` and ``vStep`` are the sampling rates themselves: intervals per
    unit of the surface's knot range in that direction.
    """

    uStep = field.newField("uStep", "SFFloat", 1, 100.0)
    vStep = field.newField("vStep", "SFFloat", 1, 100.0)

    def steps(self) -> tuple[float, float]:
        """The rates the node states."""
        return float(self.uStep), float(self.vStep)
