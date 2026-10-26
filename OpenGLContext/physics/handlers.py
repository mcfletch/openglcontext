"""Who hears which physics event.

A :class:`Handler` is a function registered for one kind of event, on some
bodies or on all of them, with filters. It holds the function weakly, as the
engine's other handlers are held: a bound method of a live object is called, and
one whose object has gone is dropped. A :class:`HandlerTable` finds the handlers
an event reaches and from which side.
"""
from __future__ import annotations

import threading
import weakref
from collections.abc import Callable, Iterable
from typing import Any

from OpenGLContext.physics.callbacks import is_physics_callback
from OpenGLContext.physics.records import PhysicsEvent

__all__ = ['EVENTS', 'NAME_OF', 'STEP_EVENTS', 'Handler', 'HandlerTable', 'weak_reference']

#: The event names, and the (kind, phase) of the record each one hears.
EVENTS: dict[str, tuple[str, str]] = {
    'hit': ('contact', 'begin'),
    'touching': ('contact', 'persist'),
    'separate': ('contact', 'end'),
    'enter': ('trigger', 'enter'),
    'stay': ('trigger', 'stay'),
    'exit': ('trigger', 'exit'),
    'sleep': ('state', 'sleep'),
    'wake': ('state', 'wake'),
}
#: The event name of each (kind, phase) record.
NAME_OF: dict[tuple[str, str], str] = {pair: name for name, pair in EVENTS.items()}
#: Events of the world and not of a body: they receive a :class:`Step`.
STEP_EVENTS = ('before-step', 'after-step')


def weak_reference(function: Callable[..., Any]) -> Callable[[], Callable[..., Any] | None]:
    """A weak reference to ``function``, held through its object if it is a bound method."""
    if hasattr(function, '__self__') and hasattr(function, '__func__'):
        return weakref.WeakMethod(function)
    return weakref.ref(function)


class Handler:
    """A function registered for one kind of event."""

    def __init__(self, event: str, function: Callable[..., Any],
                 bodies: Iterable[int] | None = None, other: Iterable[int] | None = None,
                 above: float = 0.0) -> None:
        if event not in EVENTS and event not in STEP_EVENTS:
            raise ValueError('unknown physics event %r; choose from %s'
                             % (event, ', '.join((*EVENTS, *STEP_EVENTS))))
        self.event = event
        self.kind, self.phase = EVENTS.get(event, ('step', event))
        self._function = weak_reference(function)
        #: True when the function is marked :func:`physics_callback`.
        self.physics = is_physics_callback(function)
        #: The body ids this handler covers, or None for every body.
        self.bodies = None if bodies is None else frozenset(bodies)
        #: The ids the other side must be one of, or None for any.
        self.other = None if other is None else frozenset(other)
        #: The closing speed a contact must exceed to be heard.
        self.above = float(above)
        self.active = True
        #: Whether the function raised; logged once per handler.
        self.failed = False
        self._detach: Callable[[Handler], None] | None = None

    def __repr__(self) -> str:
        return 'Handler(%r, %r)' % (self.event, self.function())

    def function(self) -> Callable[..., Any] | None:
        """The function, or None once its object has been collected."""
        return self._function()

    def cancel(self) -> None:
        """Stop calling the function. Cancelling twice is harmless."""
        self.active = False
        if self._detach is not None:
            detach, self._detach = self._detach, None
            detach(self)

    def hears(self, event: PhysicsEvent, side: int) -> bool:
        """Whether ``event``, seen from ``side`` (0 for ``a``, 1 for ``b``), is one this handler asked for."""
        if event.kind != self.kind or event.phase != self.phase:
            return False
        mine = event.a if side == 0 else event.b
        other = event.b if side == 0 else event.a
        if mine is None:
            return False
        if self.bodies is not None and mine not in self.bodies:
            return False
        if self.other is not None and other not in self.other:
            return False
        return not (event.kind == 'contact' and event.phase in ('begin', 'persist')
                    and not event.approach > self.above)


class HandlerTable:
    """The handlers of one service, safe to read from the worker while the render thread edits."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: tuple[Handler, ...] = ()

    def __len__(self) -> int:
        return len(self._handlers)

    def add(self, handler: Handler) -> Handler:
        """Register ``handler``; returns it."""
        with self._lock:
            self._handlers = (*self._handlers, handler)
        handler._detach = self._remove
        return handler

    def _remove(self, handler: Handler) -> None:
        with self._lock:
            self._handlers = tuple(h for h in self._handlers if h is not handler)

    def prune(self) -> None:
        """Drop the handlers whose function has been collected or that were cancelled."""
        with self._lock:
            self._handlers = tuple(h for h in self._handlers
                                   if h.active and h.function() is not None)

    def forget_body(self, uid: int) -> None:
        """End the handlers whose every body has gone, after a body is removed."""
        with self._lock:
            kept = []
            for handler in self._handlers:
                if handler.bodies is not None and uid in handler.bodies:
                    remaining = handler.bodies - {uid}
                    if not remaining:
                        handler.active = False
                        continue
                    handler.bodies = remaining
                kept.append(handler)
            self._handlers = tuple(kept)

    def named(self, event: str, bodies: Iterable[int] | None = None) -> list[Handler]:
        """The handlers for ``event`` covering exactly ``bodies`` (None for every body)."""
        wanted = None if bodies is None else frozenset(bodies)
        return [h for h in self._handlers if h.event == event and h.bodies == wanted]

    def any_for(self, event: str) -> bool:
        """Whether an active handler for ``event`` is registered, for any body or every body."""
        return any(h.active and h.event == event for h in self._handlers)

    def audience(self, event: PhysicsEvent, physics: bool) -> list[tuple[Handler, int]]:
        """The handlers that hear ``event`` and from which side, running on the thread named.

        A handler covering both sides hears the event once, from the first.
        """
        heard: list[tuple[Handler, int]] = []
        for handler in self._handlers:
            if not handler.active or handler.physics != physics:
                continue
            for side in (0, 1):
                if handler.hears(event, side):
                    heard.append((handler, side))
                    break
        return heard

    def has_step_handlers(self) -> bool:
        """Whether a live ``'before-step'`` or ``'after-step'`` handler is registered."""
        return any(h.active and h.event in STEP_EVENTS for h in self._handlers)

    def of_step(self, event: str) -> list[Handler]:
        """The live handlers for ``'before-step'`` or ``'after-step'``."""
        return [h for h in self._handlers if h.event == event and h.active]
