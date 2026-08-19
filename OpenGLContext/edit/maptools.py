"""Tools that drive a plan view rather than what is drawn on it.

An editor's pointer is shared: it draws, and it moves the map. Where a tool
wants only some of the pointer the camera picks up the rest -- that is what
:class:`~OpenGLContext.edit.tools.ToolManager` is for -- but a designer also
wants to say "just move the map" and have the drawing tool stop guessing. That
is a mode of its own, and this is it.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

from OpenGLContext.edit.mapview import MapView
from OpenGLContext.edit.tools import Pointer, ToolMode

__all__ = ['PanTool']


class PanTool(ToolMode):
    """Dragging the map about with the pointer.

    The world goes with the pointer, so what was under it stays under it. The
    drag is measured from where the pointer last was rather than from where it
    started, because the map moves underneath it and a fixed origin would make
    the map accelerate away.
    """

    def __init__(self, view: MapView,
                 viewport: Callable[[], Tuple[int, int]],
                 on_change: Optional[Callable[[], None]] = None,
                 **named: Any) -> None:
        named.setdefault('name', 'pan')
        named.setdefault('label', 'Pan/zoom')
        super().__init__(**named)
        self.view = view
        #: Where the window's size comes from, asked each time: it changes.
        self.viewport = viewport
        #: Called after the map has moved.
        self.on_change = on_change
        self._from: Optional[Tuple[float, float]] = None

    def cancel(self) -> None:
        self._from = None

    def on_press(self, pointer: Pointer) -> bool:
        if pointer.button:
            return False
        self._from = (float(pointer.x), float(pointer.y))
        return True

    def on_drag(self, pointer: Pointer) -> bool:
        if self._from is None:
            return False
        self.view.pan(float(pointer.x) - self._from[0],
                      float(pointer.y) - self._from[1], self.viewport())
        self._from = (float(pointer.x), float(pointer.y))
        if self.on_change is not None:
            self.on_change()
        return True

    def on_release(self, pointer: Pointer) -> bool:
        taken = self._from is not None
        self._from = None
        return taken
