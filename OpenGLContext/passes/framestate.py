"""What one frame of a render pass has worked out, for that frame alone.

A frame walks the scene once (:class:`~OpenGLContext.passes._flat.GatheredPaths`)
and several of its stages read the walk: each view's cull, the shadow pass's
caster pool, every mirror view and every zone capture. The walk describes the
scene as it stood when it was made, so it is held here, and the pass drops
this object when the frame ends -- in a ``finally``, so a frame that raised
leaves nothing for the next one to read by mistake.

:meth:`OpenGLContext.passes._flat.FlatPass.drawingFrame` opens one around a
frame; ``frameState`` on the pass is the open one, or None between frames.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    import numpy as np

    from OpenGLContext.passes._flat import GatheredPaths

__all__ = ('FrameState',)


class FrameState:
    """The state one frame shares among its stages."""

    __slots__ = ('gathered', 'reach', 'refusesShare')

    def __init__(self) -> None:
        #: This frame's walk of the scene, once it has been made.
        self.gathered: Optional['GatheredPaths'] = None
        #: Where each shape of the walk is and how far it reaches, the world
        #: centres and radii of :func:`~OpenGLContext.passes.reflection.reach`,
        #: once a mirror view has asked.
        self.reach: Optional[Tuple['np.ndarray', 'np.ndarray']] = None
        #: Per path of the walk, whether a mirror view drawing it draws it
        #: apart from a shared draw: 1 yes, 0 no, -1 not asked yet.
        self.refusesShare: Optional['np.ndarray'] = None
