"""OpenGLContext events built from Pygame's events

The event classes and the key-name translation the Pygame window system
(:mod:`OpenGLContext.windowsystem.pygame`) builds its events with.
"""

import re
from typing import Any, ClassVar

from OpenGLContext.events import mouseevents, keyboardevents
from OpenGLContext.events.mouseevents import WHEEL_BUTTONS
import pygame
from pygame.locals import *
# Named as well as starred: the star import is how a pygame program is written,
# but these three are the only names read here and a checker cannot see them
# through it.
from pygame.locals import KMOD_ALT, KMOD_CTRL, KMOD_SHIFT
import logging

log = logging.getLogger(__name__)

#: Keys SDL names in a way the general rule below does not reach.  The keypad's
#: own Enter is the return key, and the last three are named for what they do
#: rather than for the legend on the cap, as X11 and wx name them.
KEY_NAMES: dict[str, str] = {
    'space': ' ',
    'enter': '<return>',
    'break': '<pause>',
    'scroll lock': '<scroll>',
    'left meta': '<start>',
    'right meta': '<start>',
}

#: The numeric keypad, which SDL brackets: ``[0]``, ``[/]``.  A digit becomes
#: ``#0`` and an operator the character it produces, which is how the other
#: backends spell them.
KEYPAD = re.compile(r'^\[(.)\]$')

#: A function key, which SDL spells in lower case and OpenGLContext in upper.
FUNCTION_KEY = re.compile(r'^<f\d+>$')


def modifierState() -> tuple[bool, bool, bool]:
    """The (shift, ctrl, alt) triple as the keyboard stands now"""
    mods = pygame.key.get_mods()
    return (bool(mods & KMOD_SHIFT), bool(mods & KMOD_CTRL),
            bool(mods & KMOD_ALT))


class PygameXEvent(object):
    """Base class for all Pygame-specific event types

    Provides functions for determining the modifier state,
    and for translating key names between the two standards

    Attributes:
        CURRENTBUTTONSTATES -- tracks the current state of the
            mouse buttons, a three-value list
    """

    CURRENTBUTTONSTATES: ClassVar[list[int]] = [0, 0, 0]

    def _getModifiers(self) -> tuple[bool, bool, bool]:
        "get the state of the keyboard modifiers"
        return modifierState()

    def _translateKey(self, name: str) -> str:
        """The OpenGLContext name of a key SDL has named

        The vocabulary is the one
        :meth:`~OpenGLContext.events.keyboardevents.KeyboardEventManager.registerCallback`
        documents, which is what every other backend produces, so a binding
        written once works whichever backend opened the window.
        """
        if len(name) <= 1:
            return name
        special = KEY_NAMES.get(name)
        if special is not None:
            return special
        keypad = KEYPAD.match(name)
        if keypad is not None:
            character = keypad.group(1)
            return ('#' + character) if character.isdigit() else character
        if name not in ("left", "right"):
            # SDL names a paired key by its side ("left shift"); a binding asks
            # for shift.  The arrow keys are called "left" and "right" outright
            # and keep their names.
            name = name.replace("left", "").replace("right", "")
        name = "<" + name.replace(" ", "") + ">"
        if FUNCTION_KEY.match(name):
            return name.upper()
        return name

    def _updateButtons(self, button: int, state: int) -> int:
        """Update the tracked state for mouse buttons

        pygame is 1+ context button IDs
        """
        for local, pg in ((0, 1), (1, 3), (2, 2)):
            if button == pg:
                self.CURRENTBUTTONSTATES[local] = state
                return local
        # A wheel notch is one of the buttons no physical mouse has, and never
        # enters the held-button state: no wheel is ever down, so a drag begun
        # by one would have nothing to end it.
        if button - 1 not in WHEEL_BUTTONS:
            log.warning(
                """Unrecognised button: %s""",
                button,
            )
        return button - 1


class PygameMouseButtonEvent(PygameXEvent, mouseevents.MouseButtonEvent):
    """Pygame-specific mouse-button state change event"""

    def __init__(self, context: Any, PygameEventObject: Any,
                 state: int = 0) -> None:
        super(PygameMouseButtonEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        self.state = state
        # is this right?
        self.button = self._updateButtons(PygameEventObject.button, state)
        relx, rely = PygameEventObject.pos
        self.pickPoint = relx, context.getViewPort()[1] - rely


class PygameMouseMoveEvent(PygameXEvent, mouseevents.MouseMoveEvent):
    """Pygame-specific mouse-movement event"""

    def __init__(self, context: Any, PygameEventObject: Any) -> None:
        super(PygameMouseMoveEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        buttons = []
        for index in range(len(self.CURRENTBUTTONSTATES)):
            if self.CURRENTBUTTONSTATES[index]:
                buttons.append(index)
        self.buttons = tuple(buttons)
        relx, rely = PygameEventObject.pos
        self.pickPoint = relx, context.getViewPort()[1] - rely


class PygameKeyboardEvent(PygameXEvent, keyboardevents.KeyboardEvent):
    """Pygame-specific keyboard (character) event"""

    def __init__(self, context: Any, PygameEventObject: Any,
                 state: int = 0) -> None:
        super(PygameKeyboardEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        self.name = self._translateKey(pygame.key.name(PygameEventObject.key))
        self.state = state


class PygameKeypressEvent(PygameXEvent, keyboardevents.KeypressEvent):
    """Pygame-specific key-press (or release) event"""

    def __init__(self, context: Any, PygameEventObject: Any) -> None:
        super(PygameKeypressEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        # note: this is wrong, should translate according to modifiers etceteras...
        self.name = self._translateKey(PygameEventObject.unicode)
