"""Module providing translation from GLFW callbacks to OpenGLContext events"""

from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
from OpenGLContext.events.mouseevents import (
    WHEEL_BUTTONS, WHEEL_DOWN, WHEEL_UP,
)
import glfw
import math
import os
import time
import logging

log = logging.getLogger(__name__)

#: How near a whole wheel notch counts as one, for a touchpad reporting
#: fractions whose sum lands a rounding error short.
WHEEL_TOLERANCE = 1e-3

#: What one click of a wheel is assumed to report until a report says
#: otherwise.  **It is not the same everywhere**: GLFW gives a continuous
#: offset and no count of detents, X11 reports 1.0 for one click, and the
#: Wayland backend divides the protocol's 15.0 by ten and reports 1.5.
WHEEL_DETENT = 1.0

#: Below this an offset is a touchpad reporting *part* of a click rather than a
#: wheel reporting a whole one, and is summed instead.  A fraction that small
#: is also no evidence about how big a click is on this platform.
WHEEL_DETENT_MINIMUM = 0.5

#: Set this to have every scroll callback say what it was given and what it
#: made of it.  **Backends and compositors disagree about how a wheel reaches
#: an application**, and a compositor that reports one physical detent twice is
#: indistinguishable from a quick flick of the wheel unless somebody can see
#: the offsets themselves -- so this is what turns "the wheel skips a step"
#: into a number.  Off unless asked for: a line per notch would be a line per
#: notch for ever.
WHEEL_DEBUG_ENV = 'OPENGLCONTEXT_DEBUG_WHEEL'


class EventHandlerMixin(eventhandlermixin.EventHandlerMixin):
    """GLFW-specific EventHandlerMixin sub-class

    Adds the various callbacks for GLFW's events to
    translate them to OpenGLContext events.
    """

    # Software key-repeat. GLFW's Wayland platform only emits glfw.REPEAT when
    # the compositor advertises repeat_info, which a nested/container compositor
    # often does not -- so holding a key delivers PRESS then nothing, breaking
    # held-key navigation. We synthesise repeats from PRESS..RELEASE, disabling
    # it the moment a native glfw.REPEAT proves the platform delivers its own.
    keyRepeatDelay = 0.4        # seconds held before the first synthetic repeat
    keyRepeatInterval = 0.05    # seconds between synthetic repeats (~20/s)
    _nativeRepeat = False

    def _heldKeys(self):
        held = self.__dict__.get('_heldKeysMap')
        if held is None:
            held = self.__dict__['_heldKeysMap'] = {}
        return held

    ### KEYBOARD interactions
    def glfwOnKey(self, window, key, scancode, action, mods):
        """Convert a key event to a context-style event"""
        if action == glfw.PRESS:
            self._heldKeys()[key] = [mods, time.time() + self.keyRepeatDelay]
            self._emitKey(key, 1, mods)
        elif action == glfw.RELEASE:
            self._heldKeys().pop(key, None)
            self._emitKey(key, 0, mods)
        elif action == glfw.REPEAT:
            self._nativeRepeat = True   # platform delivers repeat; stop faking it
            self._emitKey(key, 1, mods)

    def _emitKey(self, key, state, mods):
        self.ProcessEvent(GLFWKeyboardEvent(self, key, state, mods))

    def pumpKeyRepeats(self):
        """Emit synthetic key-repeat events for currently-held keys.

        Called once per main-loop iteration. A no-op once native repeat is seen
        or when no key is held.
        """
        held = self.__dict__.get('_heldKeysMap')
        if self._nativeRepeat or not held:
            return
        now = time.time()
        for key, info in list(held.items()):
            if now >= info[1]:
                self._emitKey(key, 1, info[0])
                info[1] = now + self.keyRepeatInterval

    def clearHeldKeys(self):
        """Drop held-key state (e.g. on focus loss, where RELEASE may not come)."""
        self.__dict__.pop('_heldKeysMap', None)

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
    def _cursorToFramebuffer(self, window, x, y):
        """Scale a GLFW cursor position to framebuffer pixels.

        GLFW reports the cursor in logical window coordinates, but the viewport
        and the selection buffer are sized in physical framebuffer pixels (see
        GLFWContext, which sets the viewport from get_framebuffer_size). On a
        HiDPI / scaled display the two differ, so feeding the raw cursor position
        into the pick point lands the pick on the wrong pixel -- clicking an
        object misses while clicking a scaled-away offset hits. Scale by the
        framebuffer-to-window ratio so the pick point matches what was rendered.
        """
        win_w, win_h = glfw.get_window_size(window)
        fb_w, fb_h = glfw.get_framebuffer_size(window)
        if win_w and win_h:
            x = x * fb_w / win_w
            y = y * fb_h / win_h
        return x, y

    def glfwOnMouseButton(self, window, button, action, mods):
        """Convert mouse-press-or-release to a Context-style event"""
        state = 1 if action == glfw.PRESS else 0
        x, y = glfw.get_cursor_pos(window)
        x, y = self._cursorToFramebuffer(window, x, y)
        self.addPickEvent(
            GLFWMouseButtonEvent(self, button, state, int(x), int(y), mods)
        )
        self.triggerPick()

    def glfwOnScroll(self, window, xoffset, yoffset):
        """Convert scrolling to the pair of button events a wheel notch is.

        GLFW reports scrolling on a callback of its own, in offsets rather than
        in the wheel buttons everything downstream reads (see
        :data:`~OpenGLContext.events.mouseevents.WHEEL_UP`), so each whole notch
        becomes a press and a release here.  Only the vertical offset is used:
        nothing in the interface scrolls sideways.
        """
        notches = self._wheelNotches(yoffset)
        if os.environ.get(WHEEL_DEBUG_ENV):
            log.info('wheel: reported %+.4f, carrying %+.4f, sending %d notch(es)',
                     float(yoffset), getattr(self, '_wheelRemainder', 0.0),
                     len(notches))
        for button in notches:
            self._emitWheel(window, button)

    def _wheelNotches(self, offset):
        """The notches in one report: a wheel's clicks, or a touchpad's sum.

        **The two are different devices and are counted differently.**  A wheel
        reports a whole click at a time, in whatever units this platform
        measures a click in; a touchpad reports a stream of parts of one, which
        are summed so that a slow drag scrolls once it has asked for a whole
        notch and a fast one scrolls no further than it was pushed.  What
        separates them is :data:`WHEEL_DETENT_MINIMUM`.

        Assuming a click is 1.0 is what made every *other* click of a Wayland
        wheel scroll twice: 1.5 is one notch with half of one carried, and the
        next 1.5 makes 2.0 and fires two.  So the size of a click is
        :meth:`_wheelDetentSize`'s to learn.
        """
        offset = float(offset)
        if not offset:
            return []
        button = WHEEL_UP if offset > 0.0 else WHEEL_DOWN
        if abs(offset) >= WHEEL_DETENT_MINIMUM:
            return [button] * self._wheelClicks(abs(offset))
        return [button] * self._padNotches(offset)

    def _wheelClicks(self, size: float) -> int:
        """How many clicks of the wheel one report of ``size`` is.

        The size of a click is **learned from what arrives**, because GLFW
        offers no count of detents and the platforms disagree.  A report that
        is not a whole number of the click we assumed is itself the evidence
        that the assumption was wrong, and is one click of a smaller size.

        A wheel does not inherit a touchpad's carried fraction: they are two
        devices, and half a drag over a pad must not turn the next click of the
        wheel into two.
        """
        detent = getattr(self, '_wheelDetent', WHEEL_DETENT)
        clicks = size / detent
        whole = int(round(clicks))
        if whole < 1 or abs(clicks - whole) > WHEEL_TOLERANCE:
            self._wheelDetent = size
            whole = 1
        self._wheelRemainder = 0.0
        return whole

    def _padNotches(self, offset: float) -> int:
        """The whole notches in a touchpad's fraction, carrying the remainder.

        Turning back drops what was carried rather than letting a jitter over
        the pad accumulate into a notch the way it is not moving.
        """
        carried = getattr(self, '_wheelRemainder', 0.0)
        if (carried > 0.0) != (offset > 0.0):
            carried = 0.0
        total = carried + offset
        # Ten reported tenths sum to a hair under one, so a notch is anything
        # within a thousandth of whole: nobody can feel the difference, and
        # without it a steady drag loses a notch every so often for no reason
        # the user can see.
        notches = int(total + math.copysign(WHEEL_TOLERANCE, total))
        self._wheelRemainder = total - notches
        return abs(notches)

    def _emitWheel(self, window, button):
        """One notch, as the press and release of a button that is never held."""
        x, y = glfw.get_cursor_pos(window)
        x, y = self._cursorToFramebuffer(window, x, y)
        for state in (1, 0):
            self.addPickEvent(
                GLFWMouseButtonEvent(self, button, state, int(x), int(y))
            )
        self.triggerPick()

    def glfwOnCursorPos(self, window, xpos, ypos):
        """Convert mouse-movement to a Context-style event.

        The movement sampler is told directly as well as through the pick
        queue: a mouse-look mode wants every scrap of motion as it happens,
        while a pick event is only delivered once the selection buffer resolves
        it -- and not at all when the pointer is over nothing or picking is off.

        Both are told in the **same** coordinates: GLFW reports y downward and
        everything else in OpenGLContext counts it upward from the bottom, so
        the flip happens once, here.  Feeding the sampler the raw value inverts
        mouse-look's vertical and nothing else, which is about the hardest sign
        error there is to spot.
        """
        xpos, ypos = self._cursorToFramebuffer(window, xpos, ypos)
        height = self.getViewPort()[1]
        record = getattr(self, 'recordPointerMotion', None)
        if record is not None:
            record(int(xpos), height - int(ypos))
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
