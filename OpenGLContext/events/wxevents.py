"""Module providing translation from wxPython events to OpenGLContext events"""
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
from OpenGLContext.events.mouseevents import WHEEL_UP
from OpenGLContext.events.wheel import WheelNotches
import wx

log = logging.getLogger( __name__ )

#: Which of OpenGLContext's button numbers each wx button is.  OpenGLContext
#: numbers them in the X11 order -- 0 left, 1 right, 2 middle -- because the
#: wheel takes 3 and 4 there; wx numbers them left, middle, right.
BUTTON_MAPPING: Dict[int, int] = {
    wx.MOUSE_BTN_LEFT: 0,
    wx.MOUSE_BTN_RIGHT: 1,
    wx.MOUSE_BTN_MIDDLE: 2,
}

#: Which wx predicate answers whether each of those buttons is down now, for a
#: drag, where wx names no button at all and the event has to be asked about
#: each one.  The numbers are :data:`BUTTON_MAPPING`'s, so a drag reports the
#: button its press did.
BUTTON_IS_DOWN: Tuple[Tuple[int, str], ...] = (
    (0, 'LeftIsDown'),
    (1, 'RightIsDown'),
    (2, 'MiddleIsDown'),
)


class EventHandlerMixin( eventhandlermixin.EventHandlerMixin):
    """wxPython-specific event handler mix-in

    Basically provides translation from wxPython events
    to their OpenGLContext-specific equivalents (the
    concrete versions of which are also defined in this
    module).
    """
    #: Counts a stream of wheel reports into whole notches; wx states its own
    #: detent size on the event, so the counter is built on the first one.
    _wheelCounter: Optional[WheelNotches] = None

    if TYPE_CHECKING:
        # What this mix-in needs of the wx canvas beside it.
        def addPickEvent(self, event: Any) -> Any: ...
        def triggerPick(self) -> Any: ...
        def getViewPort(self) -> Tuple[int, int]: ...

    ### KEYBOARD interactions
    def wxOnKeyDown( self, event: Any ) -> None:
        '''Convert a key-press to a context-style event'''
        code = event.GetKeyCode()
        if code in self.heldKeys():
            self.noteNativeRepeat()     # already down, so wx is repeating it
        self.noteKeyDown( code, _modifiersOf( event ) )
        self.ProcessEvent( wxKeyboardEvent( self, event, 1))
        event.Skip()
    def wxOnKeyUp( self, event: Any ) -> None:
        '''Convert a key-release to a context-style event'''
        self.noteKeyUp( event.GetKeyCode() )
        self.ProcessEvent( wxKeyboardEvent( self, event, 0))
    def wxOnCharacter( self, event: Any ) -> None:
        """Convert character (non-control) press to context event"""
        self.ProcessEvent( wxKeypressEvent( self, event))
    def wxOnKillFocus( self, event: Any ) -> None:
        """Let go of every held key as the canvas loses focus

        No key-up arrives for a key that was down when focus went elsewhere, so
        without this the key stays held for the rest of the session and the
        camera keeps moving with nobody touching the keyboard.
        """
        self.clearHeldKeys()
        event.Skip()
    def emitKey( self, key: Any, state: int, modifiers: Any ) -> None:
        """Send a key transition the window system did not report

        ``modifiers`` is the triple that came with the press, so the synthetic
        release matches the binding the press did; see
        :class:`OpenGLContext.events.eventhandlermixin.HeldKeyMixin`.
        """
        made = wxKeyboardEvent.__new__( wxKeyboardEvent )
        keyboardevents.KeyboardEvent.__init__( made )
        if hasattr( self, 'currentPass' ):
            made.renderingPass = self.currentPass
        made.modifiers = modifiers
        made.name = keyName( key )
        made.state = state
        self.ProcessEvent( made )
    ### MOUSE Interaction
    def wxOnMouseButton(self, event: Any ) -> None:
        """Convert mouse-button event to context event"""
        self.addPickEvent( wxMouseButtonEvent( self, event))
        self.triggerPick()
    def wxOnMouseMove(self, event: Any ) -> None:
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
        x, y = event.GetX(), event.GetY()
        echo = self.pointerWarpEcho( x, y )
        record = getattr( self, 'recordPointerMotion', None )
        if record is not None:
            if echo:
                forget = getattr( self, 'forgetPointerOrigin', None )
                if forget is not None:
                    forget()
            record( int(x), self.getViewPort()[1] - int(y) )
        if echo:
            return
        self.recentrePointer()
        self.addPickEvent( wxMouseMoveEvent( self, event))
        self.triggerPick()
    def wxOnMouseWheel(self, event: Any ) -> None:
        """Convert scrolling to the pair of button events a wheel notch is

        wx reports scrolling as an amount of rotation rather than as the wheel
        buttons everything downstream reads (see
        :data:`~OpenGLContext.events.mouseevents.WHEEL_UP`), so each whole
        notch becomes a press and a release here.  Only vertical rotation is
        used: nothing in the interface scrolls sideways.
        """
        if event.GetWheelAxis() != wx.MOUSE_WHEEL_VERTICAL:
            return
        if self._wheelCounter is None:
            self._wheelCounter = WheelNotches( event.GetWheelDelta() or 120 )
        for button in self._wheelCounter.notches( event.GetWheelRotation() ):
            for state in (1, 0):
                self.addPickEvent(
                    wxWheelEvent( self, event, button=button, state=state ) )
        self.triggerPick()
    def pointerWarpEcho( self, x: int, y: int ) -> bool:
        """Whether this movement is one the window itself caused

        Answered by the canvas, which is what does the warping; see
        :meth:`OpenGLContext.wxcontext.wxContext.pointerWarpEcho`.  A window
        that never warps the pointer never sees an echo.
        """
        return False
    def recentrePointer( self ) -> None:
        """Put a grabbed pointer back in the middle of the window

        Answered by the canvas; see
        :meth:`OpenGLContext.wxcontext.wxContext.recentrePointer`.  A window
        with no pointer capture has nothing to do here.
        """


def _modifiersOf( wxEventObject: Any ) -> Tuple[bool, bool, bool]:
    """The shift, control and alt triple a wx event was delivered with

    A function rather than a method on the event classes, because the canvas
    reads it too: a key it has to *hold* is remembered with the modifiers its
    press carried, so the release focus loss never delivered matches the
    binding the press matched.
    """
    return (
        not(not( wxEventObject.ShiftDown())),
        not(not( wxEventObject.ControlDown())),
        not(not( wxEventObject.AltDown())),
    )


def keyName( code: int ) -> str:
    """The OpenGLContext name of the key a wx key code is

    :data:`keyboardMapping` names the keys wx has a constant for, and the
    characters below 256.  Anything else is named by its code, so that two keys
    the table does not list -- the keypad's Enter and the Windows key, say --
    are still two different keys rather than one binding between them.
    """
    return keyboardMapping.get( code, '<unknown-%d>' % (code,) )

class wxXEvent(object):
    """Base-class for all wxPython-specific event classes

    Provides method for determining the modifier set from
    wxPython event objects
    """
    def _getModifiers( self, wxEventObject: Any) -> Tuple[bool, bool, bool]:
        """Get a three-tupple of shift, control, alt status"""
        return _modifiersOf( wxEventObject )

class wxMouseButtonEvent( wxXEvent, mouseevents.MouseButtonEvent ):
    """wxPython-specific mouse button event"""
    def __init__( self, context: Any, wxEventObject: Any ) -> None:
        super (wxMouseButtonEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(wxEventObject)
        wxButton = wxEventObject.GetButton()
        self.button = BUTTON_MAPPING.get( wxButton, -1 )
        if self.button < 0:
            # wx answers MOUSE_BTN_NONE for anything that is not a button
            # changing state, and there is then no press or release to report.
            log.warning( """Unrecognised wx mouse button: %s""", wxButton )
        else:
            self.state = int( bool( wxEventObject.ButtonDown( wxButton ) ) )
        self.pickPoint = wxEventObject.GetX(), context.getViewPort()[1]- wxEventObject.GetY()
        
class wxWheelEvent( wxXEvent, mouseevents.MouseButtonEvent ):
    """One notch of the wheel, as the press and release of a button

    Separate from :class:`wxMouseButtonEvent` because a wx wheel event names no
    button at all: the button is which way the wheel turned, which the caller
    has already worked out.
    """
    def __init__( self, context: Any, wxEventObject: Any,
                  button: int = WHEEL_UP, state: int = 0 ) -> None:
        super (wxWheelEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(wxEventObject)
        self.button = button
        self.state = state
        self.pickPoint = wxEventObject.GetX(), context.getViewPort()[1]- wxEventObject.GetY()

class wxMouseMoveEvent( wxXEvent, mouseevents.MouseMoveEvent ):
    """wxPython-specific mouse movement event"""
    def __init__( self, context: Any, wxEventObject: Any ) -> None:
        super (wxMouseMoveEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(wxEventObject)
        buttons = []
        for local, method in BUTTON_IS_DOWN:
            if getattr( wxEventObject, method )():
                buttons.append( local )
        self.buttons = tuple( sorted( buttons ) )
        self.pickPoint = wxEventObject.GetX(), context.getViewPort()[1]- wxEventObject.GetY()

class wxKeyboardEvent( wxXEvent, keyboardevents.KeyboardEvent ):
    """wxPython-specific keyboard event"""
    def __init__( self, context: Any, wxEventObject: Any, state: int = 0 ) -> None:
        super (wxKeyboardEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(wxEventObject)
        self.name = keyName( wxEventObject.GetKeyCode() )
        self.state = state
class wxKeypressEvent( wxXEvent, keyboardevents.KeypressEvent ):
    """wxPython-specific key-press event"""
    def __init__( self, context: Any, wxEventObject: Any) -> None:
        super (wxKeypressEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(wxEventObject)
        self.name = keyName( wxEventObject.GetKeyCode() )

PAGE_UP = wx.WXK_PRIOR if hasattr(wx,'WXK_PRIOR') else wx.WXK_PAGEUP
PAGE_DOWN = wx.WXK_NEXT if hasattr(wx,'WXK_PRIOR') else wx.WXK_PAGEDOWN
keyboardMapping: Dict[int, str] = {
    wx.WXK_BACK:'<back>',
    wx.WXK_TAB:'<tab>',
    wx.WXK_RETURN:'<return>',
    wx.WXK_ESCAPE:'<escape>',
    wx.WXK_SPACE:' ',
    wx.WXK_DELETE:'<delete>',
    wx.WXK_START:'<start>',
##	wx.WXK_LBUTTON:
##	wx.WXK_RBUTTON:
##	wx.WXK_CANCEL:
##	wx.WXK_MBUTTON:
##	wx.WXK_CLEAR:
    wx.WXK_SHIFT:'<shift>',
    wx.WXK_CONTROL:'<ctrl>',
    wx.WXK_MENU:'<alt>',
    wx.WXK_PAUSE:'<pause>',
##	wx.WXK_CAPITAL:
    PAGE_UP:'<pageup>',
    PAGE_DOWN:'<pagedown>',
    wx.WXK_END:'<end>',
    wx.WXK_HOME:'<home>',
    wx.WXK_LEFT:'<left>',
    wx.WXK_UP:'<up>',
    wx.WXK_RIGHT:'<right>',
    wx.WXK_DOWN:'<down>',
##	wx.WXK_SELECT:
##	wx.WXK_PRINT:
##	wx.WXK_EXECUTE:
##	wx.WXK_SNAPSHOT:
    wx.WXK_INSERT:'<insert>',
##	wx.WXK_HELP:
    wx.WXK_NUMPAD0:'#0',
    wx.WXK_NUMPAD1:'#1',
    wx.WXK_NUMPAD2:'#2',
    wx.WXK_NUMPAD3:'#3',
    wx.WXK_NUMPAD4:'#4',
    wx.WXK_NUMPAD5:'#5',
    wx.WXK_NUMPAD6:'#6',
    wx.WXK_NUMPAD7:'#7',
    wx.WXK_NUMPAD8:'#8',
    wx.WXK_NUMPAD9:'#9',
    wx.WXK_MULTIPLY:'*',
    wx.WXK_ADD:'+',
    wx.WXK_SEPARATOR:'_', # ???
    wx.WXK_SUBTRACT:'-',
    wx.WXK_DECIMAL:'.',
    wx.WXK_DIVIDE:'/',
    wx.WXK_F1: '<F1>',
    wx.WXK_F2: '<F2>',
    wx.WXK_F3: '<F3>',
    wx.WXK_F4: '<F4>',
    wx.WXK_F5: '<F5>',
    wx.WXK_F6: '<F6>',
    wx.WXK_F7: '<F7>',
    wx.WXK_F8: '<F8>',
    wx.WXK_F9: '<F9>',
    wx.WXK_F10: '<F10>',
    wx.WXK_F11: '<F11>',
    wx.WXK_F12: '<F12>',
    wx.WXK_F13: '<F13>',
    wx.WXK_F14: '<F14>',
    wx.WXK_F15: '<F15>',
    wx.WXK_F16: '<F16>',
    wx.WXK_F17: '<F17>',
    wx.WXK_F18: '<F18>',
    wx.WXK_F19: '<F19>',
    wx.WXK_F20: '<F20>',
    wx.WXK_F21: '<F21>',
    wx.WXK_F22: '<F22>',
    wx.WXK_F23: '<F23>',
    wx.WXK_F24: '<F24>',
    wx.WXK_NUMLOCK: '<numlock>',
    wx.WXK_SCROLL: '<scroll>',
    13: '<return>',
}
for integer in range (256):
    if integer not in keyboardMapping:
        keyboardMapping[integer] = chr( integer ).lower()
del integer	