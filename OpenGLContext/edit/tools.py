"""Tool modes: what the pointer does, and who gets to decide.

An editor's pointer does a different thing in each tool -- placing a point,
dragging one, measuring, painting -- and the camera wants the same pointer. The
rule is that **the tool in force is asked first and the camera gets whatever
the tool did not want**, so a tool that only cares about the left button leaves
the right one orbiting.

Modelled on the movement modes in :mod:`OpenGLContext.move.navigation`: the
tools are declared, one is in force, and the manager routes to it. What differs
is that a tool is driven by *events* rather than by sampled input, because
placing a point is a thing that happens at a moment and walking forwards is a
thing that goes on.

::

    tools = ToolManager([PlacePoint(), DragPoint()])

    def ProcessEvent(self, event):
        if tools.handle(event):
            return None
        return super().ProcessEvent(event)

A tool that has taken a press keeps the pointer until the release, so a drag
that wanders off whatever started it still ends where it should, and the tool
cannot be switched out from under a gesture it is half-way through.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence, Tuple

import numpy as np

__all__ = ['Pointer', 'ToolMode', 'ToolManager']

#: Which entry of an event's modifier triple is which.
SHIFT, CONTROL, ALT = 0, 1, 2


@dataclass
class Pointer:
    """Where the pointer is: on the screen, and in the world under it.

    ``x``/``y`` are window pixels. ``world`` is the point on whatever surface
    is under the cursor, or ``None`` where the cursor is over nothing -- the
    sky, or a part of the frame the depth buffer has nothing in. ``node`` is
    what was picked there, when the caller knows.
    """

    x: float = 0.0
    y: float = 0.0
    world: Optional[np.ndarray] = None
    node: Any = None
    button: int = 0
    modifiers: Tuple[int, int, int] = (0, 0, 0)

    @property
    def on_surface(self) -> bool:
        """Whether the cursor is over something rather than over the sky."""
        return self.world is not None

    @property
    def shifted(self) -> bool:
        return bool(self.modifiers[SHIFT])

    @property
    def controlled(self) -> bool:
        return bool(self.modifiers[CONTROL])

    @property
    def alted(self) -> bool:
        return bool(self.modifiers[ALT])


@dataclass
class ToolMode:
    """One thing the pointer does.

    Every hook returns whether the tool used what it was given. The default is
    to use nothing, so a subclass that overrides one hook leaves the rest of
    the pointer to the camera rather than swallowing it.

    ``enter``/``leave`` bracket the time a tool is in force -- where a preview
    is put on screen and taken off again -- and ``cancel`` abandons a gesture
    half-way through, which is what Escape does.
    """

    name: str = ''
    #: What a menu or a toolbar calls this. Taken from the name when not given,
    #: so a tool is one line to declare and still reads properly on screen.
    label: str = ''
    #: A key that selects this tool, for a manager that offers shortcuts.
    shortcut: str = ''
    _extra: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.name.replace('_', ' ').replace('-', ' ').strip()
            self.label = self.label[:1].upper() + self.label[1:]

    # -- the time this tool is in force ------------------------------------
    def enter(self) -> None:
        """This tool has just taken the pointer."""

    def leave(self) -> None:
        """Another tool has taken it."""

    def cancel(self) -> None:
        """Abandon whatever is half-done, leaving the world as it was."""

    # -- the pointer -------------------------------------------------------
    def on_press(self, pointer: Pointer) -> bool:
        """A button went down. Taking it starts a drag that comes here."""
        return False

    def on_drag(self, pointer: Pointer) -> bool:
        """The pointer moved with the button this tool took still down."""
        return False

    def on_release(self, pointer: Pointer) -> bool:
        """The button came up, ending the drag."""
        return False

    def on_move(self, pointer: Pointer) -> bool:
        """The pointer moved with nothing held."""
        return False

    def on_key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        """A key, while this tool is in force."""
        return False

    def on_wheel(self, pointer: Pointer, notches: int) -> bool:
        """The wheel turned over the world, while this tool is in force.

        Taking it is how a brush is resized without a key: the camera gets the
        notch otherwise, which is what a wheel does everywhere else.
        """
        return False

    # -- taking it back ----------------------------------------------------
    def undo(self) -> bool:
        """Take back the last thing this tool did. False if there was none.

        Undo belongs to the tool because the tools edit different things: a
        route, a landscape, a set of markers. One history over all of them
        would take back whichever change came last regardless of what the
        designer is working on.
        """
        return False

    def redo(self) -> bool:
        """Do again what :meth:`undo` took back."""
        return False


class ToolManager:
    """The tool in force, and the routing that gives it first refusal."""

    def __init__(self, tools: Sequence[ToolMode] = (),
                 on_change: Optional[Callable[[Optional[ToolMode]], None]] = None
                 ) -> None:
        self.tools: List[ToolMode] = list(tools)
        #: Called with the tool that has just taken the pointer.
        self.on_change = on_change
        self.active: Optional[ToolMode] = self.tools[0] if self.tools else None
        #: The tool part-way through a gesture, and the button that started it.
        self._dragging: Optional[ToolMode] = None
        self._button = 0
        if self.active is not None:
            self.active.enter()

    # -- choosing ----------------------------------------------------------
    def named(self, name: str) -> Optional[ToolMode]:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def select(self, name: str) -> bool:
        """Put a tool in force. False if there is no such tool, or a gesture
        is part-way through: a tool switched out mid-drag never sees the end of
        what it started."""
        tool = self.named(name)
        if tool is None or self._dragging is not None:
            return False
        if tool is self.active:
            return True
        if self.active is not None:
            self.active.leave()
        self.active = tool
        tool.enter()
        if self.on_change is not None:
            self.on_change(tool)
        return True

    def cycle(self, step: int = 1) -> Optional[ToolMode]:
        """Move to the next declared tool, coming round at the ends."""
        if not self.tools:
            return None
        if self.active is None:
            self.select(self.tools[0].name)
            return self.active
        index = (self.tools.index(self.active) + int(step)) % len(self.tools)
        self.select(self.tools[index].name)
        return self.active

    # -- routing -----------------------------------------------------------
    def press(self, pointer: Pointer) -> bool:
        tool = self.active
        if tool is None or not tool.on_press(pointer):
            return False
        self._dragging = tool
        self._button = int(pointer.button)
        return True

    def move(self, pointer: Pointer) -> bool:
        if self._dragging is not None:
            pointer.button = self._button
            return self._dragging.on_drag(pointer)
        tool = self.active
        return bool(tool is not None and tool.on_move(pointer))

    def release(self, pointer: Pointer) -> bool:
        dragging, self._dragging = self._dragging, None
        if dragging is None:
            active = self.active
            return bool(active is not None and active.on_release(pointer))
        pointer.button = self._button
        return dragging.on_release(pointer)

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name == '<escape>' and self._dragging is not None:
            dragging, self._dragging = self._dragging, None
            dragging.cancel()
            return True
        tool = self.active
        return bool(tool is not None and tool.on_key(name, modifiers))

    def wheel(self, pointer: Pointer, notches: int) -> bool:
        tool = self.active
        return bool(tool is not None and tool.on_wheel(pointer, int(notches)))

    # -- taking it back ----------------------------------------------------
    def undo(self) -> bool:
        """Ask the tool in force to take back what it last did."""
        tool = self.active
        return bool(tool is not None and tool.undo())

    def redo(self) -> bool:
        """Ask the tool in force to do it again."""
        tool = self.active
        return bool(tool is not None and tool.redo())
