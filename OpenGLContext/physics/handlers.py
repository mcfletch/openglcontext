"""Who hears which physics event.

A :class:`Handler` is a function registered for one kind of event, on some
bodies or on all of them, with filters. It holds the function weakly, as the
engine's other handlers are held: a bound method of a live object is called, and
one whose object has gone is dropped. A :class:`HandlerTable` finds the handlers
an event reaches and from which side, looking only at the handlers of the
event's kind and phase on its two bodies and on every body.
"""
from __future__ import annotations

import itertools
import threading
import weakref
from collections.abc import Callable, Iterable
from typing import Any, NamedTuple

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
    'impact': ('vehicle', 'impact'),
    'crash': ('vehicle', 'crash'),
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
        #: Its place in the order handlers are registered in, set by :meth:`HandlerTable.add`.
        self.order = 0
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
        gated = event.kind == 'vehicle' or (event.kind == 'contact'
                                            and event.phase in ('begin', 'persist'))
        return not (gated and not event.approach > self.above)


#: Numbers each handler registered, in order.
_registrations = itertools.count(1)


def _registered(handler: Handler) -> int:
    return handler.order


class _Audience(NamedTuple):
    """The handlers of one (kind, phase, thread): by each body they cover, and those covering every body."""
    by_body: dict[int, tuple[Handler, ...]]
    everyone: tuple[Handler, ...]


class HandlerTable:
    """The handlers of one service, safe to read from the worker while the render thread edits.

    The handlers are a tuple replaced whole on each change. :meth:`audience`
    reads an index of them by (kind, phase, thread) and by body, built again
    on the first read after a change.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: tuple[Handler, ...] = ()
        self._index: dict[tuple[str, str, bool], _Audience] | None = None

    def __len__(self) -> int:
        return len(self._handlers)

    def _set(self, handlers: tuple[Handler, ...]) -> None:
        """Hold ``handlers``, the lock held; the index is built again when next read."""
        self._handlers = handlers
        self._index = None

    def add(self, handler: Handler) -> Handler:
        """Register ``handler``; returns it."""
        with self._lock:
            handler.order = next(_registrations)
            self._set((*self._handlers, handler))
        handler._detach = self._remove
        return handler

    def _remove(self, handler: Handler) -> None:
        with self._lock:
            self._set(tuple(h for h in self._handlers if h is not handler))

    def prune(self) -> None:
        """Drop the handlers whose function has been collected or that were cancelled."""
        with self._lock:
            kept = tuple(h for h in self._handlers if h.active and h.function() is not None)
            if len(kept) != len(self._handlers):
                self._set(kept)

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
            self._set(tuple(kept))

    def _indexed(self) -> dict[tuple[str, str, bool], _Audience]:
        """The index of the handlers, built from the tuple held where a change cleared it."""
        index = self._index
        if index is not None:
            return index
        with self._lock:
            if self._index is None:
                by_body: dict[tuple[str, str, bool], dict[int, list[Handler]]] = {}
                everyone: dict[tuple[str, str, bool], list[Handler]] = {}
                for handler in self._handlers:
                    key = (handler.kind, handler.phase, handler.physics)
                    if handler.bodies is None:
                        everyone.setdefault(key, []).append(handler)
                        continue
                    table = by_body.setdefault(key, {})
                    for uid in handler.bodies:
                        table.setdefault(uid, []).append(handler)
                self._index = {
                    key: _Audience({uid: tuple(found) for uid, found in by_body.get(key, {}).items()},
                                   tuple(everyone.get(key, ())))
                    for key in by_body.keys() | everyone.keys()}
            return self._index

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
        Handlers are listed in the order they were registered.
        """
        audience = self._indexed().get((event.kind, event.phase, physics))
        if audience is None:
            return []
        candidates = list(audience.everyone)
        for uid in (event.a, event.b):
            if uid is not None:
                candidates.extend(audience.by_body.get(uid, ()))
        if len(candidates) > 1:
            candidates = sorted(set(candidates), key=_registered)
        heard: list[tuple[Handler, int]] = []
        for handler in candidates:
            if not handler.active:
                continue
            for side in (0, 1):
                if handler.hears(event, side):
                    heard.append((handler, side))
                    break
        return heard

    def has_physics_handlers(self) -> bool:
        """Whether a live handler of a body's events runs on the physics thread."""
        return any(h.active and h.physics and h.event not in STEP_EVENTS for h in self._handlers)

    def has_step_handlers(self) -> bool:
        """Whether a live ``'before-step'`` or ``'after-step'`` handler is registered."""
        return any(h.active and h.event in STEP_EVENTS for h in self._handlers)

    def of_step(self, event: str) -> list[Handler]:
        """The live handlers for ``'before-step'`` or ``'after-step'``."""
        return [h for h in self._handlers if h.event == event and h.active]
