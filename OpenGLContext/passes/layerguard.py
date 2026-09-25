"""Switching an optional part of a frame off when it fails.

Reflections, zone probe captures and similar layers add to a frame that is
complete without them. When one raises -- a driver refusing a framebuffer
format, a value no layer can draw with -- the frame is still drawn without
it: :class:`LayerGuard` logs the failure once, with its traceback, runs the
layer's own clean-up, and runs nothing more for that layer until
:meth:`LayerGuard.reset` is called::

    self._reflection_guard = LayerGuard('planar reflection',
                                        off=self._reflectionsOff)
    ...
    self._reflection_guard.run(self._drawReflections, frames, lighting)

The layer stays off until something calls :meth:`~LayerGuard.reset`. A
failure in one frame recurs in the next as a rule, and a layer retried every
frame would log and cost every frame.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Optional, TypeVar

log = logging.getLogger(__name__)

__all__ = ['LayerGuard']

T = TypeVar('T')


class LayerGuard:
    """Runs one optional frame layer, and switches it off at its first failure.

    ``name`` is what the log calls the layer. ``off`` is called once, after
    the failure is logged, to leave the frame as it would be without the
    layer -- clear what the layer had published for others to read. ``logger``
    is where the failure is logged; this module's where none is given.
    """

    def __init__(self, name: str, off: Optional[Callable[[], None]] = None,
                 logger: Optional[logging.Logger] = None) -> None:
        self.name = name
        self.off = off
        self.logger = logger or log
        #: The exception that switched the layer off, or None while it is on.
        self.error: Optional[BaseException] = None

    @property
    def failed(self) -> bool:
        """Whether the layer has failed and is off."""
        return self.error is not None

    def run(self, layer: Callable[..., T], *args: Any, **named: Any) -> Optional[T]:
        """``layer(*args, **named)``, or None where it raised or has raised before."""
        if self.error is not None:
            return None
        try:
            return layer(*args, **named)
        except Exception as error:
            self.fail(error)
            return None

    def fail(self, error: BaseException) -> None:
        """Switch the layer off for ``error``: log it and run :attr:`off`.

        For a layer whose failure is found some way other than an exception
        out of :meth:`run`. A second call leaves the first error in place.
        """
        if self.error is not None:
            return
        self.error = error
        self.logger.error('the %s layer failed and is switched off; frames are '
                          'drawn without it: %s', self.name, error,
                          exc_info=(type(error), error, error.__traceback__))
        if self.off is not None:
            self.off()

    def reset(self) -> None:
        """Switch the layer back on, for its next frame to try again."""
        self.error = None
