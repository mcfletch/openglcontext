"""Module providing translation from Tkinter events to OpenGLContext events"""

from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP
from OpenGLContext.events.wheel import WheelNotches

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
#: needs no counting; see :meth:`EventHandlerMixin.tkOnMouseButton`.
WHEEL_DELTA = 120.0

#: Which Tk button number is which of OpenGLContext's.  Tk numbers them 1, 2,
#: 3 for left, middle, right; OpenGLContext numbers them 0, 2, 1, since it
#: keeps the X11 order where the wheel is 4 and 5.
BUTTON_MAPPING = {1: 0, 2: 2, 3: 1}

#: The Tk button numbers a wheel notch arrives on under X11, and which way each
#: turns.
X11_WHEEL_BUTTONS = {4: WHEEL_UP, 5: WHEEL_DOWN}


class EventHandlerMixin( eventhandlermixin.EventHandlerMixin):
    """Tkinter-specific event handler mix-in

    Basically provides translation from Tkinter events
    to their OpenGLContext-specific equivalents (the
    concrete versions of which are also defined in this
    module).
    """
    #: Counts a stream of ``<MouseWheel>`` reports into whole notches.
    _wheelCounter = None

    ### KEYBOARD interactions
    def tkOnKeyDown( self, event ):
        '''Convert a key-press to a context-style event'''
        name = keyName( event )
        if name in self.heldKeys():
            self.noteNativeRepeat()     # already down, so Tk is repeating it
        self.noteKeyDown( name, modifiersOf( event ) )
        self.ProcessEvent( tkKeyboardEvent( self, event, 1))
        if event.char:
            self.ProcessEvent( tkKeypressEvent( self, event))

    def tkOnKeyUp( self, event ):
        '''Convert a key-release to a context-style event'''
        self.noteKeyUp( keyName( event ) )
        self.ProcessEvent( tkKeyboardEvent( self, event, 0))

    def tkOnCharacter( self, event ):
        """Convert character (non-control) press to context event"""
        self.ProcessEvent( tkKeypressEvent( self, event))

    def tkOnFocusOut( self, event ):
        """Let go of every held key as the widget loses focus

        No key-up arrives for a key that was down when focus went elsewhere, so
        without this the key stays held for the rest of the session and the
        camera keeps moving with nobody touching the keyboard.
        """
        self.clearHeldKeys()

    def emitKey( self, key, state, modifiers ):
        """Send a key transition the window system did not report

        ``modifiers`` is the triple that came with the press, so the synthetic
        release matches the binding the press did; see
        :class:`OpenGLContext.events.eventhandlermixin.HeldKeyMixin`.
        """
        made = tkKeyboardEvent.__new__( tkKeyboardEvent )
        keyboardevents.KeyboardEvent.__init__( made )
        if hasattr( self, 'currentPass' ):
            made.renderingPass = self.currentPass
        made.modifiers = modifiers
        made.name = key
        made.state = state
        self.ProcessEvent( made )

    ### MOUSE Interaction
    def tkOnMouseButton(self, event ):
        """Convert mouse-button event to context event

        A wheel notch arrives here on X11, where Tk reports it as a press of
        button 4 or 5; on Windows and macOS it arrives as ``<MouseWheel>``
        instead (:meth:`tkOnMouseWheel`).
        """
        if event.num in X11_WHEEL_BUTTONS:
            self._postWheel( event, X11_WHEEL_BUTTONS[event.num] )
            return
        self.addPickEvent( tkMouseButtonEvent( self, event, state=1))
        self.triggerPick()

    def tkOnMouseRelease( self, event ):
        """Convert release-of-mouse event to context event"""
        if event.num in X11_WHEEL_BUTTONS:
            return                      # the notch was delivered by the press
        self.addPickEvent( tkMouseButtonEvent( self, event, state=0))
        self.triggerPick()

    def tkOnMouseWheel( self, event ):
        """Convert a Windows or macOS wheel report to notches

        Tk states the rotation there rather than naming a button, so each whole
        notch becomes the press and release of one; see
        :data:`~OpenGLContext.events.mouseevents.WHEEL_UP`.
        """
        if self._wheelCounter is None:
            self._wheelCounter = WheelNotches( WHEEL_DELTA )
        for button in self._wheelCounter.notches( getattr(event, 'delta', 0) ):
            self._postWheel( event, button )

    def _postWheel( self, event, button ):
        """One notch, as the press and release of a button that is never held"""
        for state in (1, 0):
            self.addPickEvent(
                tkWheelEvent( self, event, button=button, state=state ) )
        self.triggerPick()

    def tkOnMouseMove(self, event ):
        """Convert mouse-movement event to context event

        The movement sampler is told directly as well as through the pick
        queue: a mouse-look mode wants every scrap of motion as it happens,
        while a pick event is only delivered once the selection buffer resolves
        it -- and not at all when the pointer is over nothing or picking is off.

        A movement the window made itself -- the warp that keeps a grabbed
        pointer in the middle of the window -- updates where the pointer is and
        goes no further: it is not motion the user asked for, and it is not a
        click on anything.
        """
        echo = self.pointerWarpEcho( event.x, event.y )
        record = getattr( self, 'recordPointerMotion', None )
        if record is not None:
            if echo:
                forget = getattr( self, 'forgetPointerOrigin', None )
                if forget is not None:
                    forget()
            record( int(event.x), self.getViewPort()[1] - int(event.y) )
        if echo:
            return
        self.recentrePointer()
        self.addPickEvent( tkMouseMoveEvent( self, event))
        self.triggerPick()

    def pointerWarpEcho( self, x, y ):
        """Whether this movement is one the window itself caused

        Answered by the context, which is what does the warping; see
        :meth:`OpenGLContext.tkcontext.TkContext.pointerWarpEcho`.  A window
        that never warps the pointer never sees an echo.
        """
        return False

    def recentrePointer( self ):
        """Put a grabbed pointer back in the middle of the window

        Answered by the context; see
        :meth:`OpenGLContext.tkcontext.TkContext.recentrePointer`.  A window
        with no pointer capture has nothing to do here.
        """


def modifiersOf( tkEventObject ):
    """The shift, control and alt triple a Tk event was delivered with

    A function rather than a method on the event classes, because the context
    reads it too: a key it has to *hold* is remembered with the modifiers its
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


def keyName( tkEventObject ):
    """The OpenGLContext name of the key a Tk event is about

    Tk names a key by its X keysym, which is what :data:`keyboardMapping`
    translates; anything else is named by the character it produced.
    """
    name = keyboardMapping.get( tkEventObject.keysym )
    if name:
        return name
    if tkEventObject.char:
        return tkEventObject.char
    return '<%s>' % (tkEventObject.keysym,)


class tkXEvent(object):
    """Base-class for all tkPython-specific event classes

    Provides method for determining the modifier set from
    Tkinter event objects
    """
    def _getModifiers( self, tkEventObject):
        """Get a three-tupple of shift, control, alt status"""
        return modifiersOf( tkEventObject )

class tkMouseButtonEvent( tkXEvent, mouseevents.MouseButtonEvent ):
    """Tkinter-specific mouse button state change event"""
    def __init__( self, context, tkEventObject, state=1 ):
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
    def __init__( self, context, tkEventObject, button=WHEEL_UP, state=0 ):
        super (tkWheelEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        self.button = button
        self.state = state
        self.pickPoint = tkEventObject.x, context.getViewPort()[1] - tkEventObject.y

class tkMouseMoveEvent( tkXEvent, mouseevents.MouseMoveEvent ):
    """Tkinter-specific mouse movement event"""
    def __init__( self, context, tkEventObject ):
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
    def __init__( self, context, tkEventObject, state=0 ):
        super (tkKeyboardEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        self.name = keyName( tkEventObject )
        self.state = state

class tkKeypressEvent( tkXEvent, keyboardevents.KeypressEvent ):
    """Tkinter-specific key-press event"""
    def __init__( self, context, tkEventObject):
        super (tkKeypressEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        self.name = tkEventObject.char


keyboardMapping = {
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
