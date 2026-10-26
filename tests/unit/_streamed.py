"""A collider source added to a standalone physics service and moved by hand.

The tests of the engine's sources (the ground, the road, the props) ask where
the surface is after the focus has moved. :class:`Streamed` holds the source in
an inline :class:`~OpenGLContext.physics.service.Physics`, moves the focus with
:meth:`Streamed.update` and answers the world the bodies are in.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition


class Streamed:
    """``source`` in a service of its own, its focus at :attr:`at`."""

    def __init__(self, source: Any) -> None:
        self.source = source
        self.physics = Physics(PhysicsDefinition(mode='inline', colliders='none'))
        self.at: tuple[float, ...] = (0.0, 0.0, 0.0)
        self.handle = self.physics.add_collider_source(source, focus=lambda: self.at)

    def update(self, at: Sequence[float]) -> None:
        """Move the focus to ``at`` and run one frame of the service, which asks the source."""
        self.at = tuple(float(v) for v in np.asarray(at, dtype='d').reshape(-1)[:3])
        self.physics.frame(0.0)
        self.physics.flush()

    def clear(self) -> None:
        """Remove the source and every body it made."""
        self.handle.remove()
        self.physics.flush()

    @property
    def world(self) -> Any:
        """The service's world, with every waiting command applied."""
        self.physics.flush()
        return self.physics.world

    def __getattr__(self, name: str) -> Any:
        return getattr(self.source, name)
