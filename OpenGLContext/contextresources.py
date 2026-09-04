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
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List

log = logging.getLogger(__name__)

__all__ = [
    'on_context_lost',
    'forget_context_lost',
    'context_lost',
    'context_key',
]

#: Callables to run as a context is destroyed, in the order they registered.
_callbacks: List[Callable[[], None]] = []


def context_key() -> Any:
    """An identifier for the GL context that is current, or ``None``.

    What every cache here keys on, and what a callback compares against to know
    whether the context going away is the one it holds objects for.  It is the
    platform's own handle, so it is only unique among *live* contexts -- which
    is why letting go as a context dies is what makes it trustworthy.
    """
    try:
        from OpenGL import contextdata

        return contextdata.getContext()
    except Exception:                   # pragma: no cover - no GL at all
        return None


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
