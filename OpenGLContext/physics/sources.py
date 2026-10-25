"""Collider sources: bodies that come and go with a point of interest.

Ground chunks near a car, road sections, props, tunnel tiles: a world too large
to hold at once makes its colliders as the focus nears them and drops them as it
leaves. A source is any object with ``update(focus)`` returning a :class:`Changes`::

    class Tiles:
        def update(self, focus):
            return Changes(add=[(key, proxy, position, orientation), ...],
                           remove=[key, ...])

``key`` is anything hashable that names a collider to the source. The service
calls ``update`` once a frame with the position of the focus, makes a static body
for each addition and removes the body of each key in ``remove``. A source
returns only what changed.
"""
from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.proxy import Proxy
    from OpenGLContext.physics.service import Physics

__all__ = ['Changes', 'ColliderSource', 'SourceHandle']


@dataclass
class Changes:
    """What a source changed since it was last asked.

    Each addition is ``(key, proxy, position, orientation)``; ``orientation`` is
    a quaternion ``(x, y, z, w)`` or None for none.
    """
    add: Sequence[tuple[Hashable, Proxy, Sequence[float], Sequence[float] | None]] = field(
        default_factory=list)
    remove: Sequence[Hashable] = field(default_factory=list)


class ColliderSource(Protocol):
    """What the service asks of a source."""

    def update(self, focus: Sequence[float]) -> Changes:
        """The colliders to add and to drop now that the focus is at ``focus``."""
        ...


class SourceHandle:
    """A source added to a service; :meth:`remove` takes it and its bodies out."""

    def __init__(self, physics: Physics, source: Any, focus: Callable[[], Sequence[float]]) -> None:
        self.physics = physics
        self.source = source
        self.focus = focus
        self.bodies: dict[Hashable, Body] = {}
        self.active = True

    def update(self) -> None:
        """Ask the source what changed and make it so."""
        changes = self.source.update(tuple(float(v) for v in self.focus()))
        for key in changes.remove:
            body = self.bodies.pop(key, None)
            if body is not None:
                self.physics.remove(body)
        for key, proxy, position, orientation in changes.add:
            if key not in self.bodies:
                self.bodies[key] = self.physics._add_placed('static', proxy, position, orientation)

    def remove(self) -> None:
        """Stop asking, and remove every body the source made. Removing twice is harmless."""
        if not self.active:
            return
        self.active = False
        for body in self.bodies.values():
            self.physics.remove(body)
        self.bodies.clear()
        if self in self.physics._sources:
            self.physics._sources.remove(self)
