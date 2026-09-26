"""Choosing which movement mode is in force, and driving it.

A context declares its modes in its definition's ``navigation``
(:class:`~OpenGLContext.move.navigationdefinition.Navigation`); this manager
decides which one applies each frame and hands it the sampled input.

Two things pick the mode, and one outranks the other.  The player *selects*
walk or fly.  The world *imposes* swimming: a mode whose
:meth:`~OpenGLContext.move.modes.MovementMode.enter_when` is true takes over
for as long as that stays true, and the player's own choice is remembered and
restored when it stops — surfacing from water puts you back in the mode you
were in, not in whichever happened to be first.

The mode in force is published as ``navigation.current``, an ``SFNode`` like
any other, so anything that wants to react — a swim overlay, a HUD label, a
sound — watches that field, or adds itself to :attr:`NavigationManager.listeners`.

The classic navigation (:class:`~OpenGLContext.move.modes.ExamineMode`) is
declared among the modes but is not driven from here: it moves the camera from
events, through the context's free-fly manager, and a walking context hands
the camera back to it when walking stops.
"""

from collections.abc import Callable, Sequence
from typing import Any, Optional

from .modes import KeyBinding, MovementMode

#: What a listener is told: the mode now in force, or None.
Listener = Callable[[Optional[MovementMode]], None]


class NavigationManager:
    """Selects and drives the movement mode for one context.

    ``definition`` is the context's
    :class:`~OpenGLContext.contextdefinition.ContextDefinition`, whose
    ``navigation`` is read each time, so a navigation assigned later is the
    one managed; ``platform`` is what the modes move.
    """

    def __init__(self, definition: Any, platform: Any) -> None:
        self.definition = definition
        self.platform = platform
        #: Called with the mode in force each time it changes.
        self.listeners: list[Listener] = []
        #: What the player chose, remembered across world-imposed modes.
        self._selected: Optional[MovementMode] = None
        first = self._initial()
        if first is not None:
            self._selected = first
            self._publish(first)

    def _initial(self) -> Optional[MovementMode]:
        """The mode the navigation names to start in, else the first selectable"""
        choices = self._selectable()
        wanted = str(getattr(self.navigation, 'mode', '') or '')
        for mode in choices:
            if mode.name == wanted:
                return mode
        return choices[0] if choices else None

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
    @property
    def navigation(self) -> Any:
        """The navigation declaration managed, or None"""
        return getattr(self.definition, 'navigation', None) or None

    def modes(self) -> Sequence[MovementMode]:
        """The declared modes that move a body; the classic navigation is not one"""
        navigation = self.navigation
        return list(navigation.movingModes()) if navigation is not None else []

    @property
    def userSwitching(self) -> tuple[str, ...]:
        """How the user may change the mode: ``keys``, ``controls``, or neither.

        What the key binding and the on-screen selector consult.  It governs
        what the user is offered, never what the application may do:
        :meth:`select` and :meth:`cycle` work whatever this says.
        """
        navigation = self.navigation
        return tuple(navigation.modeSwitching) if navigation is not None else ()

    def _selectable(self) -> list[MovementMode]:
        """Modes the player may choose: enabled, and not world-imposed.

        A mode that *can* impose itself is excluded whether or not it applies
        right now, because cycling into water movement while standing on dry
        land is not a thing a player wants.  Asked of the class rather than of
        the world, so this settles which modes are on the menu without a call
        into the platform for each one, every frame.
        """
        return [mode for mode in self.modes()
                if mode.enabled and not self._imposable(mode)]

    def selectable(self) -> list[MovementMode]:
        """The modes a selector offers, in declared order"""
        return self._selectable()

    @staticmethod
    def _imposable(mode: MovementMode) -> bool:
        """Whether the mode decides for itself when it applies."""
        return type(mode).enter_when is not MovementMode.enter_when

    @property
    def current(self) -> Optional[MovementMode]:
        """The mode in force, as last published"""
        navigation = self.navigation
        return (navigation.current or None) if navigation is not None else None

    def _publish(self, mode: Optional[MovementMode]) -> None:
        navigation = self.navigation
        if navigation is None or (navigation.current or None) is mode:
            return
        navigation.current = mode
        for listener in list(self.listeners):
            listener(mode)

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
        if self._selected in choices:
            index = choices.index(self._selected)
        else:
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
    def binding_table(self) -> list[tuple[str, KeyBinding]]:
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
