"""Module providing translation from pygame events to OpenGLContext events"""

import re
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
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
KEY_NAMES: Dict[str, str] = {
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
    _pygameWalked: Optional[Tuple[int, int]] = None

    if TYPE_CHECKING:
        # What this mix-in needs of the Pygame context beside it.
        def addPickEvent(self, event: Any) -> Any: ...
        def triggerPick(self) -> Any: ...
        def getViewPort(self) -> Tuple[int, int]: ...

    ### KEYBOARD interactions
    def PygameKeyDown(self, event: Any) -> int:
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

    def PygameKeyUp(self, event: Any) -> int:
        """Convert a key-release to a context-style event"""
        self.noteKeyUp(event.key)
        self.ProcessEvent(PygameKeyboardEvent(self, event, 0))
        return 1

    def emitKey(self, key: Any, state: int, modifiers: Any) -> None:
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

    def PygameWindowFocusLost(self, event: Any) -> int:
        """Let go of every held key: no release arrives for one held now"""
        self.clearHeldKeys()
        return 1

    def _modifierState(self) -> Tuple[bool, bool, bool]:
        """The (shift, ctrl, alt) triple as the keyboard stands now"""
        mods = pygame.key.get_mods()
        return (bool(mods & KMOD_SHIFT), bool(mods & KMOD_CTRL),
                bool(mods & KMOD_ALT))

    ### MOUSE Interaction
    def PygameMouseButtonUp(self, event: Any) -> int:
        """Convert a mouse-button-release to a context-style event"""
        self.addPickEvent(PygameMouseButtonEvent(self, event, state=0))
        self.triggerPick()
        return 1

    def PygameMouseButtonDown(self, event: Any) -> int:
        """Convert a mouse-button-press to a context-style event"""
        self.addPickEvent(PygameMouseButtonEvent(self, event, state=1))
        self.triggerPick()
        return 1

    def PygameMouseMotion(self, event: Any) -> int:
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

    def _recordMotion(self, record: Callable[[int, int], Any],
                      event: Any) -> None:
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

    CURRENTBUTTONSTATES: List[int] = [0, 0, 0]

    def _getModifiers(self) -> Tuple[bool, bool, bool]:
        "get the state of the keyboard modifiers"
        mods = pygame.key.get_mods()
        return (
            not (not (mods & KMOD_SHIFT)),
            not (not (mods & KMOD_CTRL)),
            not (not (mods & KMOD_ALT)),
        )

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
