"""The physics events as context event types: ``context.addEventHandler('physics-hit', ...)``.

Each name in :data:`~OpenGLContext.physics.handlers.EVENTS` is registered with a
context as ``physics-<name>``, beside ``keypress`` and ``mousebutton``::

    context.addEventHandler('physics-hit', body=ball, function=self.OnBallHit)

The manager registers the handler with the context's physics service, which
delivers the event and writes it to the session journal. ``body`` is a
:class:`~OpenGLContext.physics.body.Body` or a list of them; left out, every body
is covered. The other keywords are the filters of
:meth:`Body.addEventHandler <OpenGLContext.physics.body.Body.addEventHandler>`.
"""
from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import Any

from OpenGLContext.physics.body import Body
from OpenGLContext.physics.handlers import EVENTS, Handler

__all__ = ['PhysicsEventManager', 'install']

PREFIX = 'physics-'


class PhysicsEventManager:
    """Registers handlers for one physics event with a context's physics service.

    It takes part in the context's table of event managers but is not fed events
    by the window system: the physics service delivers them itself.
    """

    def __init__(self, context: Any, event: str) -> None:
        self.event = event
        self.type = PREFIX + event
        self._context = weakref.ref(context)

    def registerCallback(self, *arguments: Any, body: Any = None,
                         function: Callable[..., Any] | None = None,
                         **filters: Any) -> Handler | None:
        """Call ``function(collision)`` when ``event`` happens to ``body``, or to any body."""
        context = self._context()
        if context is None:
            raise ReferenceError('the context this event manager belonged to has gone')
        physics = context.physics
        if body is None:
            return physics.addEventHandler(self.event, function, **filters)
        targets = [body] if isinstance(body, Body) else list(body)
        return physics._add_handler(self.event, function, targets, **filters)

    def hasReceivers(self) -> bool:
        """Whether any handler is registered for this event with the context's physics service."""
        context = self._context()
        service = None if context is None else context.__dict__.get('_physics')
        return bool(service is not None and service.handlers.named(self.event))


def install(context: Any) -> None:
    """Register every physics event with ``context``'s event system."""
    for name in EVENTS:
        context.addEventManager(PREFIX + name, PhysicsEventManager(context, name))
