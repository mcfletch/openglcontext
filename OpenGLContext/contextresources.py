"""What a GL context owns, and letting go of it when the context goes.

A GL object is a *name*, and the context that issued it is the only place that
name means anything.  So a cache holding one has to be keyed by the context --
which every cache here does.

Keying is not sufficient on its own.  The key is the context's handle, the
handle is an address, and a driver hands the same address out again for the
next context: a cache that keys on it and is never told the old context died
answers the new one with the dead one's names.  That is a black window, or a
GL_INVALID_OPERATION from a draw, and it happens only when an address is reused
-- which is to say occasionally, and nowhere near the code that caused it.

So a backend says when it is tearing a context down, with the context still
current, by calling :func:`context_lost`; anything holding that context's GL
objects registers a callback with :func:`on_context_lost` to hear about it.

    from OpenGLContext import contextresources

    contextresources.on_context_lost(drop_my_cached_objects)

The engine's own caches -- the render pass, the VRML97 programs, the text
renderers, the teapot's vertex arrays -- register themselves as they are
imported, so a backend only has to make the announcement.

Names that belong to an object rather than to a module -- a geometry node's
vertex array objects, a font's display lists -- are kept in a
:class:`ContextNames`, which holds each owner's names per context and deletes
them in the context that issued them, both when the owner is collected and
when the context is torn down.
"""
from __future__ import annotations

import logging
import threading
import weakref
from typing import Any, Callable, Dict, Hashable, Iterable, List, Optional

log = logging.getLogger(__name__)

__all__ = [
    'ContextKey',
    'on_context_lost',
    'forget_context_lost',
    'context_lost',
    'context_key',
    'current_handle',
    'ContextNames',
]

#: Callables to run as a context is destroyed, in the order they registered.
_callbacks: List[Callable[[], None]] = []

#: What :func:`context_key` hands :class:`ContextKey`, and nothing else does.
_ASKED = object()


class ContextKey:
    """The GL context that was current when :func:`context_key` was asked.

    What a per-context table is keyed on. It is made only by
    :func:`context_key`, so a table typed ``Dict[ContextKey, ...]`` cannot be
    handed an ``id()`` or a handle from somewhere else; the
    ``openglcontext_checks`` mypy plugin reports a construction written
    anywhere but here. Two keys are equal when they are for the same context.
    ``handle`` is the platform's own handle, unique only among live contexts,
    which is why a table keyed on it lets go as the context dies
    (:func:`on_context_lost`).
    """

    __slots__ = ('handle',)

    def __init__(self, handle: Hashable, key: object) -> None:
        if key is not _ASKED:
            raise TypeError('a ContextKey is made by contextresources.context_key, '
                            'not directly')
        self.handle = handle

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ContextKey) and other.handle == self.handle

    def __hash__(self) -> int:
        return hash((ContextKey, self.handle))

    def __repr__(self) -> str:
        return 'ContextKey(%r)' % (self.handle,)


def current_handle() -> Optional[Hashable]:
    """The platform's own handle for the GL context that is current, or ``None``.

    What PyOpenGL's dispatch is told a context by (``Context.bindContextResources``);
    a table keys on :func:`context_key` instead.
    """
    key = context_key()
    return None if key is None else key.handle


def context_key() -> Optional[ContextKey]:
    """The key of the GL context that is current, or ``None`` where none is.

    What every cache here keys on, and what a callback compares against to know
    whether the context going away is the one it holds objects for.
    """
    try:
        from OpenGL import contextdata

        handle = contextdata.getContext()
    except Exception:
        return None
    return ContextKey(handle, _ASKED)


def on_context_lost(callback: Callable[[], None]) -> Callable[[], None]:
    """Call ``callback`` as each GL context is torn down.

    ``callback`` takes no arguments and is run with the dying context current,
    so it may delete GL objects as well as forget them, and
    :func:`context_key` tells it which context that is.  Registering the same
    callable twice registers it once.  Returns ``callback``, so this reads as a
    decorator where that suits.

    The registry holds a strong reference for the life of the process, which is
    right for the module-level caches that register at import.  A callback bound
    to an object that does not live that long has to be handed back with
    :func:`forget_context_lost`.
    """
    if callback not in _callbacks:
        _callbacks.append(callback)
    return callback


def forget_context_lost(callback: Callable[[], None]) -> bool:
    """Stop calling ``callback``; True if it was registered.

    Safe to call for one that was not, so an object tearing itself down need
    not remember whether it got as far as registering.
    """
    try:
        _callbacks.remove(callback)
    except ValueError:
        return False
    return True


def context_lost() -> None:
    """Tell every registered cache that the current GL context is going away.

    Called by a backend while the context is still current and its window still
    whole.  One cache raising must not stop the rest from being told, since
    what is left holding a dead context's names is what the next window will
    draw with, so a failure is logged and the round continues.
    """
    for callback in list(_callbacks):
        try:
            callback()
        except Exception as err:
            log.warning(
                "Releasing GL resources for a closing context failed in %r: %s",
                getattr(callback, '__qualname__', callback), err,
            )


def _itself(entry: Any) -> Iterable[int]:
    """An entry that is a GL name on its own."""
    return (entry,)


class _Held:
    """What one owner holds: for each context, its entries by key."""

    def __init__(self) -> None:
        self.by_context: Dict[Optional[ContextKey], Dict[Hashable, Any]] = {}


class ContextNames:
    """GL names objects hold in each context, deleted in the context that issued them.

    An owner keeps its entries per context, since a name means nothing outside
    the context that issued it: :meth:`entries` answers the owner's entries for
    the context current now, and ``names(entry)`` lists the GL names one entry
    holds (by default the entry is a name). The entries hang off the owner as
    its attribute ``attribute``.

    When an owner is collected its names are queued by context, since a
    finaliser runs on whichever thread the collector does and with whatever
    context is current there; ``delete(name)`` deletes each of them the next
    time :meth:`entries` or :meth:`collect` runs with that context current.
    When a context is torn down (:func:`context_lost`) every owner's names for
    it are deleted and forgotten.

    Made once per kind of name, at module level: it registers with
    :func:`on_context_lost`, which holds it for the life of the process.

        _LISTS = ContextNames('_displayLists', lambda name: glDeleteLists(name, 1))

        lists = _LISTS.entries(font)          # this context's, made on first use
    """

    def __init__(self, attribute: str, delete: Callable[[int], None],
                 names: Callable[[Any], Iterable[int]] = _itself) -> None:
        self.attribute = attribute
        self._delete = delete
        self._names = names
        #: Every owner's entries, so a lost context's can be found and deleted.
        self._holders: 'weakref.WeakSet[_Held]' = weakref.WeakSet()
        #: Names whose owner was collected, by the context that issued them,
        #: waiting for that context to be current. Appended from a finaliser,
        #: which may run on any thread, so guarded.
        self._orphans: Dict[Optional[ContextKey], List[int]] = {}
        self._lock = threading.Lock()
        on_context_lost(self._context_lost)

    def entries(self, owner: Any) -> Optional[Dict[Hashable, Any]]:
        """``owner``'s entries for the current context; None where it cannot hold any.

        Made on first use. The names collected owners left in this context are
        deleted first.
        """
        held: Optional[_Held] = getattr(owner, self.attribute, None)
        if held is None:
            held = _Held()
            try:
                setattr(owner, self.attribute, held)
                weakref.finalize(owner, self._orphaned, held)
            except (AttributeError, TypeError):
                return None
            self._holders.add(held)
        context = context_key()
        self.collect(context)
        return held.by_context.setdefault(context, {})

    def collect(self, context: Optional[ContextKey] = None) -> None:
        """Delete the names collected owners left in ``context``, which is current.

        ``context`` defaults to :func:`context_key`.
        """
        if context is None:
            context = context_key()
        if not self._orphans.get(context):
            return
        with self._lock:
            names = self._orphans.pop(context, [])
        self._delete_all(names)

    def _orphaned(self, held: _Held) -> None:
        """Queue a collected owner's names for deletion in their own contexts."""
        with self._lock:
            for context, entries in held.by_context.items():
                self._orphans.setdefault(context, []).extend(
                    name for entry in entries.values() for name in self._names(entry))
        held.by_context.clear()

    def _context_lost(self) -> None:
        """Delete and forget every owner's names in the context going away."""
        context = context_key()
        self.collect(context)
        for held in list(self._holders):
            entries = held.by_context.pop(context, None)
            if entries:
                self._delete_all(
                    [name for entry in entries.values() for name in self._names(entry)])

    def _delete_all(self, names: Iterable[int]) -> None:
        for name in names:
            try:
                self._delete(name)
            except Exception:                   # pragma: no cover - a dying driver
                log.debug("Deleting GL name %r failed", name, exc_info=True)
