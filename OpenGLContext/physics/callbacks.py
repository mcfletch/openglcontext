"""Marking a function as one that runs on the physics thread.

Events reach a handler on the render thread unless the function is marked::

    class Game(Context):
        @physics_callback
        def OnBallHit(self, hit): ...

:func:`physics_callback` only sets an attribute on the function. Registration
reads it with :func:`is_physics_callback`; a direct call runs the function on
the calling thread like any other.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

__all__ = ['is_physics_callback', 'physics_callback']

_MARK = '_oglc_physics_callback'
F = TypeVar('F', bound=Callable[..., Any])


def physics_callback(function: F) -> F:
    """Mark ``function`` as a handler that runs on the physics thread; returns it."""
    setattr(function, _MARK, True)
    return function


def is_physics_callback(function: Any) -> bool:
    """Whether ``function`` (or the function a bound method wraps) is marked."""
    return bool(getattr(function, _MARK, False))
