"""OpenGLContext events built from GLFW's callbacks

The event classes and the key and button tables the GLFW window system
(:mod:`OpenGLContext.windowsystem.glfw`) builds its events with.
"""

from typing import Any, ClassVar

from OpenGLContext.events import mouseevents, keyboardevents
from OpenGLContext.events.mouseevents import WHEEL_BUTTONS
import glfw
import logging

log = logging.getLogger(__name__)


class GLFWXEvent(object):
    """Base class for the various GLFW event types

    Attributes:
        CURRENTBUTTONSTATES -- three-tuple of the currently-
            known button-states for the mouse, class-static
            list
    """

    CURRENTBUTTONSTATES: ClassVar[list[int]] = [0, 0, 0]

    def _getModifiers(self, modifierMask: int) -> tuple[bool, bool, bool]:
        """Get the 3-tuple of modifier booleans from GLFW modifier mask"""
        return (
            bool(modifierMask & glfw.MOD_SHIFT),
            bool(modifierMask & glfw.MOD_CONTROL),
            bool(modifierMask & glfw.MOD_ALT),
        )

    def _updateButtons(self, button: int, state: int) -> tuple[int, int]:
        """Update the global mouse-button-states with an event's data"""
        index = buttonMapping.get(button)
        if index is None:
            # A wheel notch keeps its own number and never enters the held-button
            # state: no wheel is ever down, so a drag begun by one would have
            # nothing to end it.
            if button in WHEEL_BUTTONS:
                return button, state
            log.warning(
                "Unrecognized button ID: %s",
                button,
            )
            return button, state
        else:
            self.CURRENTBUTTONSTATES[index] = state
            return index, state


class GLFWMouseButtonEvent(GLFWXEvent, mouseevents.MouseButtonEvent):
    """GLFW-specific mouse-button event"""

    def __init__(self, context: Any, button: int, state: int, x: int, y: int,
                 modifiers: Any = 0) -> None:
        super(GLFWMouseButtonEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.button, self.state = self._updateButtons(button, state)
        self.modifiers = self._getModifiers(modifiers)
        self.pickPoint = x, context.getViewPort()[1] - y


class GLFWMouseMoveEvent(GLFWXEvent, mouseevents.MouseMoveEvent):
    """GLFW-specific mouse-move event"""

    def __init__(self, context: Any, x: int, y: int,
                 modifiers: Any = 0) -> None:
        super(GLFWMouseMoveEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        buttons = []
        for index in range(len(self.CURRENTBUTTONSTATES)):
            if self.CURRENTBUTTONSTATES[index]:
                buttons.append(index)
        self.buttons = tuple(buttons)
        self.modifiers = self._getModifiers(modifiers)
        self.pickPoint = x, context.getViewPort()[1] - y


class GLFWKeyboardEvent(GLFWXEvent, keyboardevents.KeyboardEvent):
    """GLFW-specific keyboard event"""

    def __init__(self, context: Any, key: int, state: int = 1,
                 modifiers: Any = 0) -> None:
        super(GLFWKeyboardEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(modifiers)
        self.name = keyboardMapping.get(key, self._keyToChar(key))
        self.state = state

    def _keyToChar(self, key: int) -> str:
        """Convert GLFW key code to character if it's a printable key"""
        # GLFW key codes for A-Z are the same as ASCII uppercase
        if glfw.KEY_A <= key <= glfw.KEY_Z:
            return chr(key).lower()
        # GLFW key codes for 0-9 are the same as ASCII
        if glfw.KEY_0 <= key <= glfw.KEY_9:
            return chr(key)
        # Space
        if key == glfw.KEY_SPACE:
            return ' '
        # Punctuation and other printable characters
        punctuation: dict[int, str] = {
            glfw.KEY_APOSTROPHE: "'",
            glfw.KEY_COMMA: ",",
            glfw.KEY_MINUS: "-",
            glfw.KEY_PERIOD: ".",
            glfw.KEY_SLASH: "/",
            glfw.KEY_SEMICOLON: ";",
            glfw.KEY_EQUAL: "=",
            glfw.KEY_LEFT_BRACKET: "[",
            glfw.KEY_BACKSLASH: "\\",
            glfw.KEY_RIGHT_BRACKET: "]",
            glfw.KEY_GRAVE_ACCENT: "`",
        }
        if key in punctuation:
            return punctuation[key]
        # Unknown key
        return "<unknown-%d>" % key


class GLFWKeypressEvent(GLFWXEvent, keyboardevents.KeypressEvent):
    """GLFW-specific key-press event (character input)"""

    def __init__(self, context: Any, codepoint: int,
                 modifiers: Any = 0) -> None:
        super(GLFWKeypressEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        if isinstance(modifiers, tuple):
            self.modifiers = modifiers
        else:
            self.modifiers = self._getModifiers(modifiers)
        # codepoint is a Unicode code point
        self.name = chr(codepoint)


# Keyboard mapping from GLFW key codes to OpenGLContext key names
keyboardMapping: dict[int, str] = {
    glfw.KEY_F1: "<F1>",
    glfw.KEY_F2: "<F2>",
    glfw.KEY_F3: "<F3>",
    glfw.KEY_F4: "<F4>",
    glfw.KEY_F5: "<F5>",
    glfw.KEY_F6: "<F6>",
    glfw.KEY_F7: "<F7>",
    glfw.KEY_F8: "<F8>",
    glfw.KEY_F9: "<F9>",
    glfw.KEY_F10: "<F10>",
    glfw.KEY_F11: "<F11>",
    glfw.KEY_F12: "<F12>",
    glfw.KEY_LEFT: "<left>",
    glfw.KEY_RIGHT: "<right>",
    glfw.KEY_UP: "<up>",
    glfw.KEY_DOWN: "<down>",
    glfw.KEY_PAGE_UP: "<pageup>",
    glfw.KEY_PAGE_DOWN: "<pagedown>",
    glfw.KEY_HOME: "<home>",
    glfw.KEY_END: "<end>",
    glfw.KEY_INSERT: "<insert>",
    glfw.KEY_DELETE: "<delete>",
    glfw.KEY_BACKSPACE: "<backspace>",
    glfw.KEY_TAB: "<tab>",
    glfw.KEY_ENTER: "<return>",
    glfw.KEY_ESCAPE: "<escape>",
    glfw.KEY_LEFT_SHIFT: "<shift>",
    glfw.KEY_RIGHT_SHIFT: "<shift>",
    glfw.KEY_LEFT_CONTROL: "<ctrl>",
    glfw.KEY_RIGHT_CONTROL: "<ctrl>",
    glfw.KEY_LEFT_ALT: "<alt>",
    glfw.KEY_RIGHT_ALT: "<alt>",
    glfw.KEY_CAPS_LOCK: "<capslock>",
    glfw.KEY_NUM_LOCK: "<numlock>",
    glfw.KEY_SCROLL_LOCK: "<scroll>",
    glfw.KEY_PAUSE: "<pause>",
    glfw.KEY_LEFT_SUPER: "<start>",
    glfw.KEY_RIGHT_SUPER: "<start>",
    # The numeric keypad is its own set of keys, named as the Tk and wx tables
    # name them: a digit is hashed, an operator is the character it produces,
    # and its Enter is the return key.
    glfw.KEY_KP_0: "#0",
    glfw.KEY_KP_1: "#1",
    glfw.KEY_KP_2: "#2",
    glfw.KEY_KP_3: "#3",
    glfw.KEY_KP_4: "#4",
    glfw.KEY_KP_5: "#5",
    glfw.KEY_KP_6: "#6",
    glfw.KEY_KP_7: "#7",
    glfw.KEY_KP_8: "#8",
    glfw.KEY_KP_9: "#9",
    glfw.KEY_KP_DIVIDE: "/",
    glfw.KEY_KP_MULTIPLY: "*",
    glfw.KEY_KP_SUBTRACT: "-",
    glfw.KEY_KP_ADD: "+",
    glfw.KEY_KP_DECIMAL: ".",
    glfw.KEY_KP_ENTER: "<return>",
}

# Mouse button mapping from GLFW button codes to OpenGLContext button indices
buttonMapping: dict[int, int] = {
    glfw.MOUSE_BUTTON_LEFT: 0,
    glfw.MOUSE_BUTTON_RIGHT: 1,
    glfw.MOUSE_BUTTON_MIDDLE: 2,
}
