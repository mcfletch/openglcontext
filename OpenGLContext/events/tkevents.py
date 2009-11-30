"""Module providing translation from Tkinter events to OpenGLContext events"""
from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
from OpenGL.Tk import *
import time

SHIFT_FLAG     = 0x00001
CTRL_FLAG      = 0x00004
ALT_FLAG       = 0x20000
CAPS_LOCK_FLAG = 0x00002
NUM_LOCK_FLAG  = 0x00008

LEFT_DOWN_FLAG = 256
RIGHT_DOWN_FLAG = 1024
MIDDLE_DOWN_FLAG = 512

class EventHandlerMixin( eventhandlermixin.EventHandlerMixin):
    """Tkinter-specific event handler mix-in

    Basically provides translation from Tkinter events
    to their OpenGLContext-specific equivalents (the
    concrete versions of which are also defined in this
    module).
    """
    ### KEYBOARD interactions
    def tkOnKeyDown( self, event ):
        '''Convert a key-press to a context-style event'''
        self.ProcessEvent( tkKeyboardEvent( self, event, 1))
    def tkOnKeyUp( self, event ):
        '''Convert a key-release to a context-style event'''
        kbEvent = tkKeyboardEvent( self, event, 0)
        self.ProcessEvent( kbEvent )
        if event.char:
            self.ProcessEvent( tkKeypressEvent( self, event))
    def tkOnCharacter( self, event ):
        """Convert character (non-control) press to context event"""
        self.ProcessEvent( tkKeypressEvent( self, event))
    ### MOUSE Interaction
    def tkOnMouseButton(self, event ):
        """Convert mouse-button event to context event"""
        event = tkMouseButtonEvent( self, event, state=1)
        self.addPickEvent( event )
        self.triggerPick()
    def tkOnMouseRelease( self, event ):
        """Convert release-of-mouse event to context event"""
        event = tkMouseButtonEvent( self, event, state=0)
        self.addPickEvent( event )
        self.triggerPick()
        
    def tkOnMouseMove(self, event ):
        """Convert mouse-movement event to context event"""
        event = tkMouseMoveEvent( self, event)
        self.addPickEvent( event )
        self.triggerPick()

class tkXEvent(object):
    """Base-class for all tkPython-specific event classes

    Provides method for determining the modifier set from
    Tkinter event objects
    """
    def _getModifiers( self, tkEventObject):
        """Get a three-tupple of shift, control, alt status"""
        state = tkEventObject.state
        return (
            not( not( state&SHIFT_FLAG)),
            not( not( state&CTRL_FLAG)),
            not( not( state&ALT_FLAG)),
        )

class tkMouseButtonEvent( tkXEvent, mouseevents.MouseButtonEvent ):
    """Tkinter-specific mouse button event"""
    def __init__( self, context, tkEventObject, state=1 ):
        super (tkMouseButtonEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        # determine which button is down, use OpenGLContext numbering scheme
        #print 'tk num', tkEventObject.num
        self.button = {1:0,3:1,2:2}[tkEventObject.num]
        self.state = state #not not (tkEventObject.state & (( LEFT_DOWN_FLAG, RIGHT_DOWN_FLAG, MIDDLE_DOWN_FLAG)[self.button]))
        self.pickPoint = tkEventObject.x, context.getViewPort()[1] - tkEventObject.y
        
class tkMouseMoveEvent( tkXEvent, mouseevents.MouseMoveEvent ):
    """Tkinter-specific mouse movement event"""
    def __init__( self, context, tkEventObject ):
        super (tkMouseMoveEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(tkEventObject)
        buttons = []
        for (flag,index) in (
            (LEFT_DOWN_FLAG,0),
            (RIGHT_DOWN_FLAG,1),
            (MIDDLE_DOWN_FLAG,2),
        ):
            if tkEventObject.state& flag:
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
        name = keyboardMapping.get( tkEventObject.keysym)
        if name:
            self.name = name
        elif tkEventObject.char:
            self.name = tkEventObject.char
        else:
            print 'Unknown keypress event: keysym = %s keysym_num = %s'%( tkEventObject.keysym, tkEventObject.keysym_num )
            self.name = ''
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
    'BackSpace':'<back>',
    '\t':'<tab>',
    '\r':'<return>',
    'Escape':'<escape>',
    'space':' ',
    'Delete':'<delete>',
    'Win_R':'<start>',
    'Win_L':'<start>',
    
    'Shift_R':'<shift>',
    'Shift_L':'<shift>',
    'Control_L':'<ctrl>',
    'Control_R':'<ctrl>',
    'Pause':'<pause>',
##	WXK_CAPITAL:
    'Prior':'<pageup>',
    'Next':'<pagedown>',
    'End':'<end>',
    'Home':'<home>',
    'Left':'<left>',
    'Up':'<up>',
    'Right':'<right>',
    'Down':'<down>',
    'Insert':'<insert>',
##	WXK_HELP:

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
    'Return': '<return>',
}