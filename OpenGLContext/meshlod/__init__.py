"""Levels of detail built from a mesh, and what they cost to look at.

The engine can be handed a model of any density and needs coarser versions of
it. :mod:`~OpenGLContext.meshlod.chain` builds those with
:mod:`opengl_decimate`; :mod:`~OpenGLContext.meshlod.quality` says what each one
looks like against the original, which is the part that decides whether a level
is usable at all.

A level's *geometric* error is a length, and a length says nothing on its own:
a millimetre is invisible on a building and ruinous on a face. What matters is
what reaches the screen, so the measurement here is made by rendering -- the
fraction of the object's own pixels that change when a level is swapped in, at a
given distance. That number is what the switching distances are derived from.
"""

from OpenGLContext.meshlod.chain import LODChain, LODLevel, build_chain
from OpenGLContext.meshlod.quality import (
    LODProbe,
    measure_chain,
    object_pop,
    safe_distance,
    silhouette,
)

__all__ = [
    # Making the levels
    'build_chain',
    'LODChain',
    'LODLevel',
    # Finding out whether they are any good
    'LODProbe',
    'measure_chain',
    'object_pop',
    'safe_distance',
    'silhouette',
]
