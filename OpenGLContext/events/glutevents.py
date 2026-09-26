"""OpenGLContext events built from GLUT's callbacks

The event classes and the key and button tables the GLUT window system
(:mod:`OpenGLContext.windowsystem.glut`) builds its events with.
"""

from typing import Any, ClassVar

from OpenGLContext.events import mouseevents, keyboardevents
from OpenGLContext.events.mouseevents import WHEEL_BUTTONS
from OpenGL.GLUT import *
import logging

log = logging.getLogger(__name__)


class GLUTXEvent(object):
    """Base class for the various GLUT event types

    Attributes:
        CURRENTBUTTONSTATES -- three-tuple of the currently-
            known button-states for the mouse, class-static
            list
    """

    CURRENTBUTTONSTATES: ClassVar[list[int]] = [0, 0, 0]

    def _getModifiers(self, modifierMask: int) -> tuple[bool, bool, bool]:
        """Get the 3-tuple of modifier booleans"""
        return (
            not (not (GLUT_ACTIVE_SHIFT & modifierMask)),
            not (not (GLUT_ACTIVE_CTRL & modifierMask)),
            not (not (GLUT_ACTIVE_ALT & modifierMask)),
        )

    def _updateButtons(self, button: int, state: int) -> tuple[int, int]:
        """Update the global mouse-button-states with an event's data"""
        if state == GLUT_UP:
            state = 0
        else:
            state = 1
        index = {
            GLUT_LEFT_BUTTON: 0,
            GLUT_RIGHT_BUTTON: 1,
            GLUT_MIDDLE_BUTTON: 2,
        }.get(button)
        if index is None:
            # A wheel notch keeps its own number: it is not one of the buttons a
            # drag is tracked with, and flattening it to -1 would leave it
            # indistinguishable from a click on whatever the pointer is over.
            if button in WHEEL_BUTTONS:
                return button, state
            log.warning(
                "Unrecognized button ID: %s",
                button,
            )
            return -1, state
        else:
            self.CURRENTBUTTONSTATES[index] = state
            return index, state


class GLUTMouseButtonEvent(GLUTXEvent, mouseevents.MouseButtonEvent):
    """GLUT-specific mouse-button event"""

    def __init__(self, context: Any, button: int, state: int, x: int, y: int,
                 modifiers: int = 0) -> None:
        super(GLUTMouseButtonEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.button, self.state = self._updateButtons(button, state)
        self.modifiers = self._getModifiers(modifiers)
        self.pickPoint = x, context.getViewPort()[1] - y


class GLUTMouseMoveEvent(GLUTXEvent, mouseevents.MouseMoveEvent):
    """GLUT-specific mouse-move event"""

    def __init__(self, context: Any, x: int, y: int,
                 modifiers: int = 0) -> None:
        super(GLUTMouseMoveEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        buttons = []
        for index in range(len(self.CURRENTBUTTONSTATES)):
            if self.CURRENTBUTTONSTATES[index]:
                buttons.append(index)
        self.buttons = tuple(buttons)
        self.modifiers = self._getModifiers(modifiers)
        self.pickPoint = x, context.getViewPort()[1] - y


class GLUTKeyboardEvent(GLUTXEvent, keyboardevents.KeyboardEvent):
    """GLUT-specific keyboard event"""

    def __init__(self, context: Any, character: Any, x: int, y: int,
                 state: int = 1, modifiers: int = 0) -> None:
        super(GLUTKeyboardEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(modifiers)
        self.name = keyboardMapping.get(character, character)
        self.state = state


class GLUTKeypressEvent(GLUTXEvent, keyboardevents.KeypressEvent):
    """GLUT-specific key-press event"""

    def __init__(self, context: Any, character: Any, x: int, y: int,
                 modifiers: int = 0) -> None:
        super(GLUTKeypressEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(modifiers)
        self.name = keyboardMapping.get(character, character)


keyboardMapping: dict[Any, str] = {
    GLUT_KEY_F1: "<F1>",
    GLUT_KEY_F2: "<F2>",
    GLUT_KEY_F3: "<F3>",
    GLUT_KEY_F4: "<F4>",
    GLUT_KEY_F5: "<F5>",
    GLUT_KEY_F6: "<F6>",
    GLUT_KEY_F7: "<F7>",
    GLUT_KEY_F8: "<F8>",
    GLUT_KEY_F9: "<F9>",
    GLUT_KEY_F10: "<F10>",
    GLUT_KEY_F11: "<F11>",
    GLUT_KEY_F12: "<F12>",
    GLUT_KEY_LEFT: "<left>",
    GLUT_KEY_RIGHT: "<right>",
    GLUT_KEY_UP: "<up>",
    GLUT_KEY_DOWN: "<down>",
    GLUT_KEY_PAGE_UP: "<pageup>",
    GLUT_KEY_PAGE_DOWN: "<pagedown>",
    GLUT_KEY_HOME: "<home>",
    GLUT_KEY_END: "<end>",
    GLUT_KEY_INSERT: "<insert>",
    b"\015": "<return>",
    b"\011": "<tab>",
    # note the ASCII encodings
    b"\033": "<escape>",
    b"\177": "<delete>",
    b"\010": "<backspace>",
}
buttonMapping: dict[Any, int] = {
    GLUT_LEFT_BUTTON: 0,
    GLUT_RIGHT_BUTTON: 1,
    GLUT_MIDDLE_BUTTON: 2,
}
