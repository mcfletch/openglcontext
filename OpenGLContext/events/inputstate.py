"""What the user is holding down *now*, sampled rather than reacted to.

A movement controller bound to key events can only act once per event, so
holding one key and tapping another loses whichever the handler did not see —
the reason "jump while running" has to be special-cased in every game that
wants it.  An :class:`InputState` instead accumulates key-down/key-up and mouse
motion as they arrive and lets a mode ask, once per frame, what is currently
true.  Several inputs then act together with no coordination between them.

It is fed by the ordinary keyboard and mouse events every backend already
emits, so it needs nothing backend-specific: a context connects it once and
movement modes sample it.
"""

from typing import Iterable, List, Set, Tuple


class InputState:
    """Held keys, one-shot presses, and accumulated mouse motion."""

    def __init__(self) -> None:
        self._held: Set[str] = set()
        #: Shift, control and alt as of the most recent key event, whichever
        #: key it was.  **Sampled, not remembered per key**: a modifier is a
        #: thing that is true *now*, and recording the ones that happened to be
        #: down when a key was first pressed makes `ctrl` + arrow depend on
        #: which of the two the player pressed first, and leaves it applying
        #: after `ctrl` has been let go.
        self._modifierState: Tuple[int, int, int] = (0, 0, 0)
        #: Keys pressed since the last time each was sampled.  Held separately
        #: from ``_held`` so a tap that starts and ends inside one frame is not
        #: lost between samples.
        self._pressed: Set[str] = set()
        self._mouse: List[float] = [0.0, 0.0]

    # -- feeding ---------------------------------------------------------
    def process(self, event: object) -> None:
        """Record one keyboard event.

        Events carrying no ``state`` (a ``keypress``, which reports a typed
        character rather than a key transition) are not key state and are
        ignored.
        """
        state = getattr(event, 'state', None)
        name = getattr(event, 'name', None)
        if state is None or name is None:
            return
        # Every key event carries the modifiers as they stand, and both halves
        # are worth having: the key-up of Ctrl itself is what says it is no
        # longer held.
        getter = getattr(event, 'getModifiers', None)
        if getter is not None:
            mods = tuple(getter())
            self._modifierState = (mods[0], mods[1], mods[2])
        if state:
            self._held.add(name)
            self._pressed.add(name)
        else:
            self._held.discard(name)

    def mouse_moved(self, dx: float, dy: float) -> None:
        """Add relative mouse motion, in pixels."""
        self._mouse[0] += float(dx)
        self._mouse[1] += float(dy)

    def clear(self) -> None:
        """Forget everything.

        A window that loses focus never receives the matching key-up, which
        would otherwise leave a key held down for the rest of the session.
        """
        self._held.clear()
        self._pressed.clear()
        self._modifierState = (0, 0, 0)
        self._mouse[:] = [0.0, 0.0]

    # -- sampling --------------------------------------------------------
    def held(self, *names: str) -> bool:
        """Whether any of ``names`` is currently down.

        Several names because one action usually has several bindings — `w`
        and the up arrow both mean forward.
        """
        return any(name in self._held for name in names)

    def held_keys(self) -> Iterable[str]:
        """Every key currently down."""
        return tuple(self._held)

    def pressed(self, *names: str) -> bool:
        """Whether any of ``names`` was pressed since this was last asked.

        Consumed by reading, so an action bound to it fires once per press
        however many frames the key stays down — a jump, not a hover.
        """
        hit = False
        for name in names:
            if name in self._pressed:
                self._pressed.discard(name)
                hit = True
        return hit

    def axis(self, positive: Iterable[str], negative: Iterable[str]) -> float:
        """``+1``/``-1``/``0`` from two opposed sets of keys.

        Holding both cancels, which is what a player expects from pressing
        forward and back together.
        """
        return ((1.0 if self.held(*positive) else 0.0)
                - (1.0 if self.held(*negative) else 0.0))

    def modifiers(self, name: str = '') -> Tuple[int, int, int]:
        """Shift, control and alt as they stand right now.

        ``name`` is accepted and ignored: a caller asks about the modifiers
        that apply to one key, and the answer is the same for every key
        because a modifier is held or it is not.
        """
        return self._modifierState

    def mouse_delta(self) -> Tuple[float, float]:
        """Mouse motion accumulated since the last call, then reset.

        Consumed by reading: mouse-look wants how far the pointer travelled
        during the frame it is about to render, not where it ended up.
        """
        delta = (self._mouse[0], self._mouse[1])
        self._mouse[:] = [0.0, 0.0]
        return delta
