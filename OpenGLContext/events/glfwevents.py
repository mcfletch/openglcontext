"""Module providing translation from GLFW callbacks to OpenGLContext events"""

from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
import glfw
import logging

log = logging.getLogger(__name__)


class EventHandlerMixin(eventhandlermixin.EventHandlerMixin):
    """GLFW-specific EventHandlerMixin sub-class

    Adds the various callbacks for GLFW's events to
    translate them to OpenGLContext events.
    """

    ### KEYBOARD interactions
    def glfwOnKey(self, window, key, scancode, action, mods):
        """Convert a key event to a context-style event"""
        if action == glfw.PRESS:
            state = 1
        elif action == glfw.RELEASE:
            state = 0
        elif action == glfw.REPEAT:
            state = 1  # Treat repeat as press
        else:
            return

        self.ProcessEvent(
            GLFWKeyboardEvent(self, key, state, mods)
        )

    def glfwOnCharacter(self, window, codepoint):
        """Convert character input to context event"""
        mods = self._getCurrentModifiers()
        self.ProcessEvent(GLFWKeypressEvent(self, codepoint, mods))

    def _getCurrentModifiers(self):
        """Get current modifier state by polling GLFW"""
        shift = (glfw.get_key(self.window, glfw.KEY_LEFT_SHIFT) == glfw.PRESS or
                 glfw.get_key(self.window, glfw.KEY_RIGHT_SHIFT) == glfw.PRESS)
        ctrl = (glfw.get_key(self.window, glfw.KEY_LEFT_CONTROL) == glfw.PRESS or
                glfw.get_key(self.window, glfw.KEY_RIGHT_CONTROL) == glfw.PRESS)
        alt = (glfw.get_key(self.window, glfw.KEY_LEFT_ALT) == glfw.PRESS or
               glfw.get_key(self.window, glfw.KEY_RIGHT_ALT) == glfw.PRESS)
        return (shift, ctrl, alt)

    ### MOUSE Interaction
    def glfwOnMouseButton(self, window, button, action, mods):
        """Convert mouse-press-or-release to a Context-style event"""
        state = 1 if action == glfw.PRESS else 0
        x, y = glfw.get_cursor_pos(window)
        self.addPickEvent(
            GLFWMouseButtonEvent(self, button, state, int(x), int(y), mods)
        )
        self.triggerPick()

    def glfwOnCursorPos(self, window, xpos, ypos):
        """Convert mouse-movement to a Context-style event"""
        self.addPickEvent(GLFWMouseMoveEvent(self, int(xpos), int(ypos)))
        self.triggerPick()

    def glfwOnFramebufferSize(self, window, width, height):
        """Handle framebuffer resize"""
        self.OnResize(width, height)


class GLFWXEvent(object):
    """Base class for the various GLFW event types

    Attributes:
        CURRENTBUTTONSTATES -- three-tuple of the currently-
            known button-states for the mouse, class-static
            list
    """

    CURRENTBUTTONSTATES = [0, 0, 0]

    def _getModifiers(self, modifierMask):
        """Get the 3-tuple of modifier booleans from GLFW modifier mask"""
        return (
            bool(modifierMask & glfw.MOD_SHIFT),
            bool(modifierMask & glfw.MOD_CONTROL),
            bool(modifierMask & glfw.MOD_ALT),
        )

    def _updateButtons(self, button, state):
        """Update the global mouse-button-states with an event's data"""
        index = buttonMapping.get(button)
        if index is None:
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

    def __init__(self, context, button, state, x, y, modifiers=0):
        super(GLFWMouseButtonEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.button, self.state = self._updateButtons(button, state)
        self.modifiers = self._getModifiers(modifiers)
        self.pickPoint = x, context.getViewPort()[1] - y


class GLFWMouseMoveEvent(GLFWXEvent, mouseevents.MouseMoveEvent):
    """GLFW-specific mouse-move event"""

    def __init__(self, context, x, y, modifiers=0):
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

    def __init__(self, context, key, state=1, modifiers=0):
        super(GLFWKeyboardEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(modifiers)
        self.name = keyboardMapping.get(key, self._keyToChar(key))
        self.state = state

    def _keyToChar(self, key):
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
        punctuation = {
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

    def __init__(self, context, codepoint, modifiers=0):
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
keyboardMapping = {
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
}

# Mouse button mapping from GLFW button codes to OpenGLContext button indices
buttonMapping = {
    glfw.MOUSE_BUTTON_LEFT: 0,
    glfw.MOUSE_BUTTON_RIGHT: 1,
    glfw.MOUSE_BUTTON_MIDDLE: 2,
}
