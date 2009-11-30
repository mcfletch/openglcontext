"""Module providing translation from wxPython events to OpenGLContext events"""
from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
import wx
import time

class EventHandlerMixin( eventhandlermixin.EventHandlerMixin):
    """wxPython-specific event handler mix-in

    Basically provides translation from wxPython events
    to their OpenGLContext-specific equivalents (the
    concrete versions of which are also defined in this
    module).
    """
    ### KEYBOARD interactions
    def wxOnKeyDown( self, event ):
        '''Convert a key-press to a context-style event'''
        self.ProcessEvent( wxKeyboardEvent( self, event, 1))
        event.Skip()
    def wxOnKeyUp( self, event ):
        '''Convert a key-release to a context-style event'''
        self.ProcessEvent( wxKeyboardEvent( self, event, 0))
    def wxOnCharacter( self, event ):
        """Convert character (non-control) press to context event"""
        self.ProcessEvent( wxKeypressEvent( self, event))
    ### MOUSE Interaction
    def wxOnMouseButton(self, event ):
        """Convert mouse-button event to context event"""
        self.addPickEvent( wxMouseButtonEvent( self, event))
        self.triggerPick()
    def wxOnMouseMove(self, event ):
        """Convert mouse-movement event to context event"""
        self.addPickEvent( wxMouseMoveEvent( self, event))
        self.triggerPick()

class wxXEvent(object):
    """Base-class for all wxPython-specific event classes

    Provides method for determining the modifier set from
    wxPython event objects
    """
    def _getModifiers( self, wxEventObject):
        """Get a three-tupple of shift, control, alt status"""
        return (
            not(not( wxEventObject.ShiftDown())),
            not(not( wxEventObject.ControlDown())),
            not(not( wxEventObject.AltDown())),
        )

class wxMouseButtonEvent( wxXEvent, mouseevents.MouseButtonEvent ):
    """wxPython-specific mouse button event"""
    BUTTON_MAPPING = ( (0,1), (1,3), (2,2))
    def __init__( self, context, wxEventObject ):
        super (wxMouseButtonEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(wxEventObject)
        self.button = None
        for local, wx in self.BUTTON_MAPPING:
            if wx == wxEventObject.Button:
                self.button = local
                self.state = wxEventObject.ButtonDown( wx )
                break 
        if self.button is None:
            for local,wx in self.self.BUTTON_MAPPING:
                if wxEventObject.Button( wx ):
                    self.button = local
                    self.state = wxEventObject.ButtonDown( wx )
                    break
        self.pickPoint = wxEventObject.GetX(), context.getViewPort()[1]- wxEventObject.GetY()
        
class wxMouseMoveEvent( wxXEvent, mouseevents.MouseMoveEvent ):
    """wxPython-specific mouse movement event"""
    def __init__( self, context, wxEventObject ):
        super (wxMouseMoveEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(wxEventObject)
        buttons = []
        for local, method in ( (0,"LeftIsDown"), (1,"MiddleIsDown"), (2,"RightIsDown")):
            if getattr( wxEventObject, method )():
                buttons.append( local )
        self.buttons = tuple( buttons )
        self.pickPoint = wxEventObject.GetX(), context.getViewPort()[1]- wxEventObject.GetY()

class wxKeyboardEvent( wxXEvent, keyboardevents.KeyboardEvent ):
    """wxPython-specific keyboard event"""
    def __init__( self, context, wxEventObject, state=0 ):
        super (wxKeyboardEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(wxEventObject)
        self.name = keyboardMapping.get( wxEventObject.GetKeyCode())	
        self.state = state
class wxKeypressEvent( wxXEvent, keyboardevents.KeypressEvent ):
    """wxPython-specific key-press event"""
    def __init__( self, context, wxEventObject):
        super (wxKeypressEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(wxEventObject)
        self.name = keyboardMapping.get( wxEventObject.GetKeyCode())	

keyboardMapping = {
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
    wx.WXK_PRIOR:'<pageup>',
    wx.WXK_NEXT:'<pagedown>',
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
    if not integer in keyboardMapping:
        keyboardMapping[integer] = chr( integer ).lower()
del integer	