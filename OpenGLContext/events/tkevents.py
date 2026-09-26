"""OpenGLContext events built from Tkinter's events

The event classes, key table and modifier reading the Tk window system
(:mod:`OpenGLContext.windowsystem.tk`) builds its events with.
"""

from typing import Any

from OpenGLContext.events import mouseevents, keyboardevents
from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP

SHIFT_FLAG     = 0x00001
CTRL_FLAG      = 0x00004
ALT_FLAG       = 0x20000
CAPS_LOCK_FLAG = 0x00002
NUM_LOCK_FLAG  = 0x00008

LEFT_DOWN_FLAG = 256
RIGHT_DOWN_FLAG = 1024
MIDDLE_DOWN_FLAG = 512

#: What Tk reports for one notch of a wheel in a ``<MouseWheel>`` event, which
#: is what Windows and macOS deliver.  X11 delivers buttons 4 and 5 instead and
#: needs no counting; see
#: :meth:`OpenGLContext.windowsystem.tk.TkWindowSystem.onMouseButton`.
WHEEL_DELTA = 120.0

#: Which Tk button number is which of OpenGLContext's.  Tk numbers them 1, 2,
#: 3 for left, middle, right; OpenGLContext numbers them 0, 2, 1, since it
#: keeps the X11 order where the wheel is 4 and 5.
BUTTON_MAPPING: dict[int, int] = {1: 0, 2: 2, 3: 1}

#: The Tk button numbers a wheel notch arrives on under X11, and which way each
#: turns.
X11_WHEEL_BUTTONS: dict[int, int] = {4: WHEEL_UP, 5: WHEEL_DOWN}


def modifiersOf( tkEventObject: Any ) -> tuple[bool, bool, bool]:
    """The shift, control and alt triple a Tk event was delivered with

    A function rather than a method on the event classes, because the window
    system reads it too: a key it has to *hold* is remembered with the modifiers its
    press carried, so the release focus loss never delivered matches the
    binding the press matched.
    """
    state = tkEventObject.state
    if not isinstance( state, int ):
        return (False, False, False)    # a virtual event carries no state
    return (
        bool( state & SHIFT_FLAG ),
        bool( state & CTRL_FLAG ),
        bool( state & ALT_FLAG ),
    )


def keyName( tkEventObject: Any ) -> str:
    """The OpenGLContext name of the key a Tk event is about

    Tk names a key by its X keysym, which is what :data:`keyboardMapping`
    translates; anything else is named by the character it produced.
    """
    name = keyboardMapping.get( tkEventObject.keysym )
    if name:
        return name
    if tkEventObject.char:
        return str( tkEventObject.char )
    return '<%s>' % (tkEventObject.keysym,)


class tkXEvent(object):
    """Base-class for all tkPython-specific event classes

    Provides method for determining the modifier set from
    Tkinter event objects
    """
    def _getModifiers( self, tkEventObject: Any) -> tuple[bool, bool, bool]:
        """Get a three-tupple of shift, control, alt status"""
        return modifiersOf( tkEventObject )

class tkMouseButtonEvent( tkXEvent, mouseevents.MouseButtonEvent ):
    """Tkinter-specific mouse button state change event"""
    def __init__( self, context: Any, tkEventObject: Any, state: int = 1 ) -> None:
        super (tkMouseButtonEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        # OpenGLContext numbers the buttons in the X11 order, where the wheel
        # is 3 and 4, so the middle button is 2 rather than the 1 its position
        # might suggest.
        self.button = BUTTON_MAPPING.get( tkEventObject.num, tkEventObject.num )
        self.state = state
        self.pickPoint = tkEventObject.x, context.getViewPort()[1] - tkEventObject.y

class tkWheelEvent( tkXEvent, mouseevents.MouseButtonEvent ):
    """One notch of the wheel, as the press and release of a button

    Separate from :class:`tkMouseButtonEvent` because which button a notch is
    depends on the platform -- a Tk button number on X11, a rotation elsewhere
    -- and the caller has already worked it out.
    """
    def __init__( self, context: Any, tkEventObject: Any,
                  button: int = WHEEL_UP, state: int = 0 ) -> None:
        super (tkWheelEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        self.button = button
        self.state = state
        self.pickPoint = tkEventObject.x, context.getViewPort()[1] - tkEventObject.y

class tkMouseMoveEvent( tkXEvent, mouseevents.MouseMoveEvent ):
    """Tkinter-specific mouse movement event"""
    def __init__( self, context: Any, tkEventObject: Any ) -> None:
        super (tkMouseMoveEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        buttons = []
        state = tkEventObject.state if isinstance( tkEventObject.state, int ) else 0
        for (flag,index) in (
            (LEFT_DOWN_FLAG,0),
            (RIGHT_DOWN_FLAG,1),
            (MIDDLE_DOWN_FLAG,2),
        ):
            if state & flag:
                buttons.append( index )
        self.buttons = tuple( buttons )
        self.pickPoint = tkEventObject.x, context.getViewPort()[1] - tkEventObject.y

class tkKeyboardEvent( tkXEvent, keyboardevents.KeyboardEvent ):
    """Tkinter-specific keyboard event"""
    def __init__( self, context: Any, tkEventObject: Any, state: int = 0 ) -> None:
        super (tkKeyboardEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        self.name = keyName( tkEventObject )
        self.state = state

class tkKeypressEvent( tkXEvent, keyboardevents.KeypressEvent ):
    """Tkinter-specific key-press event"""
    def __init__( self, context: Any, tkEventObject: Any) -> None:
        super (tkKeypressEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        self.name = tkEventObject.char


keyboardMapping: dict[str, str] = {
    'BackSpace':'<backspace>',
    'Tab':'<tab>',
    'Return':'<return>',
    'KP_Enter':'<return>',
    'Escape':'<escape>',
    'space':' ',
    'Delete':'<delete>',
    'Insert':'<insert>',
    'Super_R':'<start>',
    'Super_L':'<start>',
    'Win_R':'<start>',
    'Win_L':'<start>',

    'Shift_R':'<shift>',
    'Shift_L':'<shift>',
    'Control_L':'<ctrl>',
    'Control_R':'<ctrl>',
    'Alt_L':'<alt>',
    'Alt_R':'<alt>',
    'Pause':'<pause>',
    'Prior':'<pageup>',
    'Next':'<pagedown>',
    'End':'<end>',
    'Home':'<home>',
    'Left':'<left>',
    'Up':'<up>',
    'Right':'<right>',
    'Down':'<down>',

    'KP_0':'#0',
    'KP_1':'#1',
    'KP_2':'#2',
    'KP_3':'#3',
    'KP_4':'#4',
    'KP_5':'#5',
    'KP_6':'#6',
    'KP_7':'#7',
    'KP_8':'#8',
    'KP_9':'#9',
    'KP_Multiply':'*',
    'KP_Add':'+',
    'KP_Subtract':'-',
    'KP_Decimal':'.',
    'KP_Divide':'/',

    'F1':'<F1>',
    'F2':'<F2>',
    'F3':'<F3>',
    'F4':'<F4>',
    'F5':'<F5>',
    'F6':'<F6>',
    'F7':'<F7>',
    'F8':'<F8>',
    'F9':'<F9>',
    'F10':'<F10>',
    'F11':'<F11>',
    'F12':'<F12>',

    'Caps_Lock': '<capslock>',
    'Num_Lock': '<numlock>',
    'Scroll_Lock': '<scroll>',
}
