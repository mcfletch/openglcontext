"""A material whose surfaces mirror the scene in their own planes.

A surface reflects the scene only when its material carries a
:class:`PlanarReflector`; a glossy material without one reflects the
image-based-lighting probe, however low its roughness, and costs nothing more.
The node is how an author opts into the cost, and its fields say how much one
mirror is worth against the others in view::

    from OpenGLContext.scenegraph.reflector import PlanarReflector

    material.reflector = PlanarReflector(interval=2)

Every shape drawn with that material is a mirror, each in the plane of its own
mesh. One reflector ``USE``\\d by the materials of a set of mirrors tunes them
together; :meth:`~OpenGLContext.scenegraph.varied.Varied.varied` gives one
mirror its own. The fields are read every frame, so a change takes effect on
the next.

How the reflections are drawn, and what they cost, is
:mod:`OpenGLContext.passes.reflection`.
"""
from __future__ import annotations

from vrml import field, node

from OpenGLContext.scenegraph.varied import Varied

__all__ = ['PlanarReflector', 'WATER', 'WATER_DISTORTION']


class PlanarReflector(Varied, node.Node):
    """A material's surfaces mirror the scene in their planes.

    ``scale`` is the reflection's resolution as a share of the mirror's
    rectangle on screen, each way. ``interval`` is the most frames a visible
    reflection goes without being drawn again; a moving object's reflection
    lags by up to that many. ``priority`` weighs this mirror against the others
    when the frame's budget is short. ``distortion`` is how far, in view
    widths, a unit of the surface normal's tilt from the plane pushes the
    lookup: water's ripple, or a mirror's normal map. ``enabled`` False keeps
    the node in place while the surface reflects the probe.

    ``replace`` True draws the reflection in place of the surface's shading
    rather than through it: the material's colour, metalness and roughness are
    not applied, and the surface shows exactly what the mirror sees. That is
    what an object-level ``mirror`` hook asks for.
    """

    PROTO = 'PlanarReflector'

    scale = field.newField('scale', 'SFFloat', 1, 0.5)
    interval = field.newField('interval', 'SFInt32', 1, 3)
    priority = field.newField('priority', 'SFFloat', 1, 1.0)
    distortion = field.newField('distortion', 'SFFloat', 1, 0.0)
    enabled = field.newField('enabled', 'SFBool', 1, True)
    replace = field.newField('replace', 'SFBool', 1, False)

    UI_HINTS = {
        'scale': {'label': 'Resolution', 'minimum': 0.05, 'maximum': 1.0,
                  'step': 0.05},
        'interval': {'label': 'Redraw every', 'minimum': 1, 'maximum': 30,
                     'step': 1},
        'priority': {'label': 'Priority', 'minimum': 0.0, 'maximum': 10.0,
                     'step': 0.1},
        'distortion': {'label': 'Distortion', 'minimum': 0.0, 'maximum': 1.0,
                       'step': 0.01},
        'enabled': {'label': 'Reflects the scene'},
        'replace': {'label': 'Shows only the reflection'},
    }


#: How far, in view widths, a unit of water's tilt from flat pushes its lookup.
#: The ripple tilts it by a tenth or so, which moves a reflected edge by a few
#: percent of the view: broken up, still legible.
WATER_DISTORTION = 0.12

#: What a body of water reflects by: redrawn every frame, since what stands on
#: a shore moves and the eye is on it. Shared, as the water styles are; a lake
#: of its own is ``WATER.varied(...)``.
WATER = PlanarReflector(interval=1, distortion=WATER_DISTORTION)
