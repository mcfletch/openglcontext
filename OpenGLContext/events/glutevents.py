"""Module providing translation from GLUT callbacks to OpenGLContext events"""

from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
from OpenGLContext.events.mouseevents import WHEEL_BUTTONS
from OpenGL.GLUT import *
import logging

log = logging.getLogger(__name__)


class EventHandlerMixin(eventhandlermixin.EventHandlerMixin):
    """Glut-specific EventHandlerMixin sub-class

    Adds the various callbacks for GLUT's events to
    translate them to OpenGLContext events.
    """

    ### KEYBOARD interactions
    def glutOnKeyDown(self, character, x, y):
        """Convert a key-press to a context-style event"""
        modifiers = glutGetModifiers()
        if character in self.heldKeys():
            self.noteNativeRepeat()     # already down, so GLUT is repeating it
        self.noteKeyDown(character, modifiers)
        self.ProcessEvent(
            GLUTKeyboardEvent(self, character, x, y, 1, modifiers)
        )

    def glutOnKeyUp(self, character, x, y):
        """Convert a key-release to a context-style event"""
        self.noteKeyUp(character)
        self.ProcessEvent(
            GLUTKeyboardEvent(self, character, x, y, 0, glutGetModifiers())
        )

    def glutOnCharacter(self, character, x, y):
        """Convert character (non-control) press to context event"""
        # need intelligence to determine what should generate a keyboard event
        # currently duplicates can occur.
        self.glutOnKeyDown(character, x, y)
        self.ProcessEvent(GLUTKeypressEvent(self, character, x, y, glutGetModifiers()))

    def emitKey(self, key, state, modifiers):
        """Send a key transition the window system did not report

        For focus loss, where GLUT delivers no release at all; see
        :class:`OpenGLContext.events.eventhandlermixin.HeldKeyMixin`.
        ``modifiers`` is the mask that came with the press, so the synthetic
        release matches the binding the press did.  A key event carries a
        pointer position that nothing reads, hence the zeroes.
        """
        self.ProcessEvent(GLUTKeyboardEvent(self, key, 0, 0, state, modifiers))

    ### MOUSE Interaction
    def glutOnMouseButton(self, button, state, x, y):
        """Convert mouse-press-or-release to a Context-style event"""
        self.addPickEvent(
            GLUTMouseButtonEvent(self, button, state, x, y, glutGetModifiers())
        )
        self.triggerPick()

    def glutOnMouseMove(self, x, y):
        """Convert mouse-movement to a Context-style event

        The movement sampler is told directly as well as through the pick
        queue: a mouse-look mode wants every scrap of motion as it happens,
        while a pick event is only delivered once the selection buffer resolves
        it -- and not at all when the pointer is over nothing or picking is off.

        A movement the window made itself -- the warp that keeps a grabbed
        pointer in the middle of the window -- updates where the pointer is and
        goes no further: it is not motion the user asked for, and it is not a
        click on anything.

        Both are told in the pick point's origin, y counting *upward* from the
        bottom, since that is what everything downstream of the context works
        in and GLUT counts it the other way.
        """
        echo = self.pointerWarpEcho(x, y)
        record = getattr(self, 'recordPointerMotion', None)
        if record is not None:
            if echo:
                forget = getattr(self, 'forgetPointerOrigin', None)
                if forget is not None:
                    forget()
            record(int(x), self.getViewPort()[1] - int(y))
        if echo:
            return
        self.recentrePointer()
        self.addPickEvent(GLUTMouseMoveEvent(self, x, y))
        self.triggerPick()

    def pointerWarpEcho(self, x, y):
        """Whether this movement is one the window itself caused

        Answered by the window, which is what does the warping; see
        :meth:`OpenGLContext.glutcontext.GLUTContext.pointerWarpEcho`.  A
        window that never warps the pointer never sees an echo.
        """
        return False

    def recentrePointer(self):
        """Put a grabbed pointer back in the middle of the window

        Answered by the window; see
        :meth:`OpenGLContext.glutcontext.GLUTContext.recentrePointer`.  A
        window with no pointer capture has nothing to do here.
        """


class GLUTXEvent(object):
    """Base class for the various GLUT event types

    Attributes:
        CURRENTBUTTONSTATES -- three-tuple of the currently-
            known button-states for the mouse, class-static
            list
    """

    CURRENTBUTTONSTATES = [0, 0, 0]

    def _getModifiers(self, modifierMask):
        """Get the 3-tuple of modifier booleans"""
        return (
            not (not (GLUT_ACTIVE_SHIFT & modifierMask)),
            not (not (GLUT_ACTIVE_CTRL & modifierMask)),
            not (not (GLUT_ACTIVE_ALT & modifierMask)),
        )

    def _updateButtons(self, button, state):
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

    def __init__(self, context, button, state, x, y, modifiers=0):
        super(GLUTMouseButtonEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.button, self.state = self._updateButtons(button, state)
        self.modifiers = self._getModifiers(modifiers)
        self.pickPoint = x, context.getViewPort()[1] - y


class GLUTMouseMoveEvent(GLUTXEvent, mouseevents.MouseMoveEvent):
    """GLUT-specific mouse-move event"""

    def __init__(self, context, x, y, modifiers=0):
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

    def __init__(self, context, character, x, y, state=1, modifiers=0):
        super(GLUTKeyboardEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(modifiers)
        self.name = keyboardMapping.get(character, character)
        self.state = state


class GLUTKeypressEvent(GLUTXEvent, keyboardevents.KeypressEvent):
    """GLUT-specific key-press event"""

    def __init__(self, context, character, x, y, modifiers=0):
        super(GLUTKeypressEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(modifiers)
        self.name = keyboardMapping.get(character, character)


keyboardMapping = {
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
buttonMapping = {
    GLUT_LEFT_BUTTON: 0,
    GLUT_RIGHT_BUTTON: 1,
    GLUT_MIDDLE_BUTTON: 2,
}
