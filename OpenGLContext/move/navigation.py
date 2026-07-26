"""Choosing which movement mode is in force, and driving it.

A context declares its modes on its :class:`ContextDefinition`; this manager
decides which one applies each frame and hands it the sampled input.

Two things pick the mode, and one outranks the other.  The player *selects*
walk or fly.  The world *imposes* swimming: a mode whose
:meth:`~OpenGLContext.move.modes.MovementMode.enter_when` is true takes over
for as long as that stays true, and the player's own choice is remembered and
restored when it stops — surfacing from water puts you back in the mode you
were in, not in whichever happened to be first.

The mode in force is published as ``ContextDefinition.movementMode``, an
``SFNode`` like any other, so anything that wants to react — a swim overlay, a
HUD label, a sound — watches that field rather than being told about it.
"""

from typing import Any, List, Optional, Sequence, Tuple

from .modes import KeyBinding, MovementMode


class NavigationManager:
    """Selects and drives the movement mode for one context."""

    def __init__(self, definition: Any, platform: Any) -> None:
        self.definition = definition
        self.platform = platform
        #: What the player chose, remembered across world-imposed modes.
        self._selected: Optional[MovementMode] = None
        first = self._selectable()
        if first:
            self._selected = first[0]
            self._publish(first[0])

    def retarget(self, platform: Any) -> None:
        """Drive a different platform, keeping the player's chosen mode.

        A character controller usually comes into being when a world finishes
        loading, after the context has already been navigating the camera.
        Building a fresh manager for it would forget which mode the player had
        chosen and publish whichever is declared first -- a silent change of
        how the controls behave, in the middle of a session.
        """
        self.platform = platform

    # -- the declared modes ----------------------------------------------
    def modes(self) -> Sequence[MovementMode]:
        return list(getattr(self.definition, 'movementModes', ()) or ())

    def _selectable(self) -> List[MovementMode]:
        """Modes the player may choose: enabled, and not world-imposed.

        A mode that *can* impose itself is excluded whether or not it applies
        right now, because cycling into water movement while standing on dry
        land is not a thing a player wants.  Asked of the class rather than of
        the world, so this settles which modes are on the menu without a call
        into the platform for each one, every frame.
        """
        return [mode for mode in self.modes()
                if mode.enabled and not self._imposable(mode)]

    @staticmethod
    def _imposable(mode: MovementMode) -> bool:
        """Whether the mode decides for itself when it applies."""
        return type(mode).enter_when is not MovementMode.enter_when

    def _publish(self, mode: Optional[MovementMode]) -> None:
        if getattr(self.definition, 'movementMode', None) is not mode:
            self.definition.movementMode = mode

    # -- selecting --------------------------------------------------------
    def select(self, name: str) -> bool:
        """Choose a mode by name; False if there is no such selectable mode."""
        for mode in self._selectable():
            if mode.name == name:
                self._selected = mode
                if not self._imposed():
                    self._publish(mode)
                return True
        return False

    def cycle(self, step: int = 1) -> Optional[MovementMode]:
        """Step to the next selectable mode and return it."""
        choices = self._selectable()
        if not choices:
            return None
        try:
            index = choices.index(self._selected)   # type: ignore[arg-type]
        except ValueError:
            index = -step
        chosen = choices[(index + step) % len(choices)]
        self._selected = chosen
        if not self._imposed():
            self._publish(chosen)
        return chosen

    def _imposed(self) -> Optional[MovementMode]:
        """The world-imposed mode that applies right now, if any."""
        for mode in self.modes():
            if mode.enabled and mode.enter_when(self.platform):
                return mode
        return None

    # -- the frame --------------------------------------------------------
    def update(self, dt: float, inputs: Any) -> Optional[MovementMode]:
        """Settle which mode is in force and give it the frame."""
        current = self._imposed() or self._selected
        if current is None:
            choices = self._selectable()
            current = choices[0] if choices else None
            self._selected = current
        self._publish(current)
        if current is not None:
            current.update(dt, inputs, self.platform)
        return current

    # -- bindings ---------------------------------------------------------
    def binding_table(self) -> List[Tuple[str, KeyBinding]]:
        """``(mode name, binding)`` for every command, for a settings window."""
        return [(mode.name, binding)
                for mode in self.modes() for binding in mode.bindings]

    def rebind(self, mode_name: str, command: str, keys: Sequence[str]) -> bool:
        """Point a command at different keys; False if it is not declared.

        Takes effect at once: modes resolve a command to keys when they sample,
        not when they are built.
        """
        for mode in self.modes():
            if mode.name != mode_name:
                continue
            for binding in mode.bindings:
                if binding.command == command:
                    binding.keys = list(keys)
                    return True
        return False
