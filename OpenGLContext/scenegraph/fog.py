"""VRML97's ``Fog`` node, rendered at last.

pyvrml97 has declared ``Fog`` since the beginning and the render pass has
collected its paths for nearly as long; nothing ever drew one.  This is that
node, working: bind it and the scene fades into :attr:`Fog.color` over
:attr:`Fog.visibilityRange`.

**Why a node rather than a number on the context.** Fog is a property of the
place the camera is standing in, and a place is a thing a scene *contains* --
so it binds, stacks and travels with a transform exactly as ``Background`` and
``Viewpoint`` do.  Being under water, inside a smoke-filled room and out in
clear air are three fogs in one scene, and only one applies at a time.

**Two curves that are not approximations of each other.** ``LINEAR`` fades in
proportion to distance; ``EXPONENTIAL`` hangs back and then closes in.  Both
reach total obscurity at ``visibilityRange``, so an author choosing between them
is choosing the shape of the fade and not its extent.  A single density number
could express only one of them, which is why the mode reaches the shader.

Reference:
    ISO/IEC 14772-1:1997 (VRML97) 6.19 ``Fog``
    https://www.web3d.org/documents/specifications/14772/V2.0/part1/nodesRef.html#Fog
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

import numpy as np
from vrml import field
from vrml.vrml97 import basenodes

#: No fog: what a node with no ``visibilityRange`` produces, and the value the
#: shader is left at for a scene that has none.
FOG_NONE = 0

#: Exponential fog by *density* rather than by range -- ``1 - exp(-density d)``.
#: Not one of VRML97's, and kept because it is the aerial-perspective curve the
#: terrain and vegetation shaders already use, where the parameter that means
#: something is a density per unit rather than a distance to nothing.
FOG_DENSITY = 1

#: VRML97 ``LINEAR``: fades in proportion to distance, gone at the range.
FOG_LINEAR = 2

#: VRML97 ``EXPONENTIAL``: hangs back, then closes in, gone at the range.
FOG_EXPONENTIAL = 3

#: ``fogType`` as the specification spells it, to the code the shader takes.
FOG_TYPES = {'LINEAR': FOG_LINEAR, 'EXPONENTIAL': FOG_EXPONENTIAL}


class Fog(basenodes.Fog):
    """A volume of coloured haze the camera is standing in.

    ``visibilityRange`` is the distance at which an object is completely
    obscured, **in this node's own coordinate system** -- so a transform above
    it scales the range, which is what lets one authored fog serve a model
    placed at two sizes.  0, the default, is no fog at all.
    """

    PROTO = 'Fog'

    #: Which of a scene's fogs is in force.  VRML97 gives a bindable node the
    #: ``set_bind`` event and the ``isBound`` eventOut but no field holding the
    #: answer, so each bindable here declares one -- the backgrounds do the
    #: same, and for the same reason: an eventOut is something you send, not
    #: something you can read back.
    bound = field.newField('bound', 'SFBool', 1, 0)

    UI_HINTS = {
        'color': {'label': 'Colour'},
        'visibilityRange': {'label': 'Visible to (m)', 'minimum': 0.0,
                            'maximum': 1000.0, 'step': 1.0},
        'fogType': {'label': 'Fade', 'options': ('LINEAR', 'EXPONENTIAL'),
                    'optionLabels': ('Steady', 'Closing in')},
    }

    def fogParameters(self, matrix: Any) -> Tuple[int, float, Tuple[float, float, float]]:
        """``(mode, density, colour)`` for the shader, from a world matrix.

        ``density`` is the **reciprocal of the visible range**, which is one
        number that serves both curves: the shader multiplies it by a
        fragment's eye distance to get how far through the fog that fragment
        lies, and each curve reads that fraction its own way.

        The scale is taken from the accumulated matrix, because the range is in
        local coordinates.  A uniform scale is what a fog is placed under in
        practice; a non-uniform one has no single answer and its longest axis is
        used, which errs toward *less* fog rather than toward a scene that
        vanishes.
        """
        visibility = float(self.visibilityRange) * _scale_of(matrix)
        if visibility <= 0.0:
            return (FOG_NONE, 0.0, self._color())
        mode = FOG_TYPES.get(str(self.fogType).upper(), FOG_LINEAR)
        return (mode, 1.0 / visibility, self._color())

    def _color(self) -> Tuple[float, float, float]:
        return tuple(float(value) for value in self.color[:3])   # type: ignore[return-value]


def _scale_of(matrix: Any) -> float:
    """The longest axis scale of a row-vector world matrix."""
    rows = np.asarray(matrix, dtype='d')[:3, :3]
    return float(max(np.linalg.norm(row) for row in rows))


def bound_fog(paths: Any) -> Optional[Any]:
    """The bound ``Fog`` path among ``paths``, or None.

    Follows what :meth:`~OpenGLContext.passes._flat.FlatPass.currentBackground`
    does for backgrounds: the first node that says it is bound wins, and with
    none bound the first found is bound and used -- so a scene that simply
    contains a fog gets it without anyone having to send ``set_bind``.
    """
    for path in paths or ():
        if path[-1].bound:
            return path
    for path in paths or ():
        path[-1].bound = 1
        return path
    return None
