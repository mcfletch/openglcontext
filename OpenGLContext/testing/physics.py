"""Test-only access to the omi_physics world inside an inline physics service.

This module exists only for the omi_physics backend, and only for tests: a
test that checks what the engine itself holds (its arrays, its materials, its
step count) reads it here. A game reads bodies through
:class:`~OpenGLContext.physics.body.Body` handles and
:meth:`Physics.poses <OpenGLContext.physics.service.Physics.poses>`, which
answer the same on every engine. Nothing here is exported by
:mod:`OpenGLContext.physics`, and the functions go away with the omi backend.
"""
from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.service import Physics

__all__ = ['body_at', 'inspect', 'run', 'slot_of']


def inspect(physics: Physics) -> Any:
    """The omi_physics ``PhysicsWorld`` of an inline ``physics``, each waiting stand-in written.

    Raises RuntimeError for a service whose world steps on its own thread.
    """
    return physics._engine_world()


def slot_of(physics: Physics, body: Body) -> int:
    """The row ``body`` has in the arrays of :func:`inspect`'s world, waiting commands applied first.

    Raises KeyError for a body the world does not hold.
    """
    return physics._slot_of(body)


def body_at(physics: Physics, slot: int) -> Body | None:
    """The body in row ``slot`` of :func:`inspect`'s world, or None for a row no body has."""
    return physics._body_at(slot)


def run(physics: Physics, function: Callable[[Any], Any]) -> concurrent.futures.Future[Any]:
    """Call ``function(world)`` with the omi_physics world on the stepping thread; the future holds its answer.

    A world with no thread running is reached on the calling thread, at once.
    """
    return physics._run(function)
