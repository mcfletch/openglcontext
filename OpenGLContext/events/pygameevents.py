"""Module providing translation from pygame events to OpenGLContext events"""

from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
from OpenGLContext.events.mouseevents import WHEEL_BUTTONS
import pygame, string
from pygame.locals import *
import logging

log = logging.getLogger(__name__)


class EventHandlerMixin(eventhandlermixin.EventHandlerMixin):
    """Pygame-specific EventHandlerMixin

    Provides mappings from Pygame events to the equivalent
    Context event classes.
    """

    #: True while the pointer is hidden and in SDL's relative mode; see
    #: :meth:`OpenGLContext.pygamecontext.PygameContext.setPointerCapture`.
    #: Read rather than asking SDL, so what the events do follows from what
    #: this context asked for.
    _pointerGrabbed = False
    #: Where the pointer would be if it had gone on moving, while it is
    #: grabbed and so no longer moving at all.
    _pygameWalked = None

    ### KEYBOARD interactions
    def PygameKeyDown(self, event):
        """Convert a key-press to a context-style event

        SDL repeats a held key for itself once
        :func:`pygame.key.set_repeat` has been called, and says so, so the
        held-key map is told and the synthetic repeat stays out of the way.
        What the map is for here is focus loss, where no release arrives at
        all; see
        :class:`OpenGLContext.events.eventhandlermixin.HeldKeyMixin`.
        """
        if event.key in self.heldKeys():
            self.noteNativeRepeat()     # already down, so this is SDL's repeat
        self.noteKeyDown(event.key, self._modifierState())
        self.ProcessEvent(PygameKeyboardEvent(self, event, 1))
        # hack, needs work!
        if event.unicode:
            self.ProcessEvent(PygameKeypressEvent(self, event))
        return 1

    def PygameKeyUp(self, event):
        """Convert a key-release to a context-style event"""
        self.noteKeyUp(event.key)
        self.ProcessEvent(PygameKeyboardEvent(self, event, 0))
        return 1

    def emitKey(self, key, state, modifiers):
        """Send a key transition the window system did not report

        The name is what the key event carries, so a synthetic release reads
        exactly as the real one would have.
        """
        made = PygameKeyboardEvent.__new__(PygameKeyboardEvent)
        keyboardevents.KeyboardEvent.__init__(made)
        made.context = self
        if hasattr(self, 'currentPass'):
            made.renderingPass = self.currentPass
        made.modifiers = modifiers
        made.name = made._translateKey(pygame.key.name(key))
        made.state = state
        self.ProcessEvent(made)

    def PygameWindowFocusLost(self, event):
        """Let go of every held key: no release arrives for one held now"""
        self.clearHeldKeys()
        return 1

    def _modifierState(self):
        """The (shift, ctrl, alt) triple as the keyboard stands now"""
        mods = pygame.key.get_mods()
        return (bool(mods & KMOD_SHIFT), bool(mods & KMOD_CTRL),
                bool(mods & KMOD_ALT))

    ### MOUSE Interaction
    def PygameMouseButtonUp(self, event):
        """Convert a mouse-button-release to a context-style event"""
        self.addPickEvent(PygameMouseButtonEvent(self, event, state=0))
        self.triggerPick()
        return 1

    def PygameMouseButtonDown(self, event):
        """Convert a mouse-button-press to a context-style event"""
        self.addPickEvent(PygameMouseButtonEvent(self, event, state=1))
        self.triggerPick()
        return 1

    def PygameMouseMotion(self, event):
        """Convert a mouse-button-move to a context-style event

        The movement sampler is told directly as well as through the pick
        queue: a mouse-look mode wants every scrap of motion as it happens,
        while a pick event is only delivered once the selection buffer resolves
        it -- and not at all when the pointer is over nothing or picking is off.

        SDL reports both where the pointer is and how far it moved, and the
        second is what a grabbed pointer has to be followed by: in relative
        mode the position stops changing while the motion does not.  Both are
        given in the pick point's origin, y counting *upward*, since that is
        what everything downstream of the context works in.
        """
        record = getattr(self, 'recordPointerMotion', None)
        if record is not None:
            self._recordMotion(record, event)
        self.addPickEvent(PygameMouseMoveEvent(self, event))
        self.triggerPick()
        return 1

    def _recordMotion(self, record, event):
        """Feed one SDL motion event to the sampler, as a position it can take
        a difference from.

        The sampler works in absolute positions and takes the delta itself, so
        a relative-mode report -- where the position no longer moves -- is
        turned back into one by accumulating SDL's ``rel`` from wherever the
        pointer last was.
        """
        height = self.getViewPort()[1]
        if self._pointerGrabbed and getattr(event, 'rel', None):
            walked = getattr(self, '_pygameWalked', None)
            if walked is None:
                walked = (event.pos[0], height - event.pos[1])
            self._pygameWalked = walked = (walked[0] + event.rel[0],
                                           walked[1] - event.rel[1])
            record(walked[0], walked[1])
            return
        self._pygameWalked = None
        record(event.pos[0], height - event.pos[1])


class PygameXEvent(object):
    """Base class for all Pygame-specific event types

    Provides functions for determining the modifier state,
    and for translating key names between the two standards

    Attributes:
        CURRENTBUTTONSTATES -- tracks the current state of the
            mouse buttons, a three-value list
    """

    CURRENTBUTTONSTATES = [0, 0, 0]

    def _getModifiers(self):
        "get the state of the keyboard modifiers"
        mods = pygame.key.get_mods()
        return (
            not (not (mods & KMOD_SHIFT)),
            not (not (mods & KMOD_CTRL)),
            not (not (mods & KMOD_ALT)),
        )

    def _translateKey(self, name):
        "Translate a key from pygame to interactivecontext"
        if len(name) > 1:
            if name[0] == "[":
                name = "#" + name[1]
            if name not in ("left", "right"):
                name = name.replace("left", "")
                name = name.replace("right", "")
            name = name.replace(" ", "")
            name = "<" + name + ">"
            if "<f1>" <= name <= "<f15>":
                name = name.upper()
        return name

    def _updateButtons(self, button, state):
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

    def __init__(self, context, PygameEventObject, state=0):
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

    def __init__(self, context, PygameEventObject):
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

    def __init__(self, context, PygameEventObject, state=0):
        super(PygameKeyboardEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        self.name = self._translateKey(pygame.key.name(PygameEventObject.key))
        self.state = state


class PygameKeypressEvent(PygameXEvent, keyboardevents.KeypressEvent):
    """Pygame-specific key-press (or release) event"""

    def __init__(self, context, PygameEventObject):
        super(PygameKeypressEvent, self).__init__()
        if hasattr(context, "currentPass"):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        # note: this is wrong, should translate according to modifiers etceteras...
        self.name = self._translateKey(PygameEventObject.unicode)
