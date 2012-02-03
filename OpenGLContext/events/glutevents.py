"""Module providing translation from GLUT callbacks to OpenGLContext events"""

from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
from OpenGL.GLUT import *

class EventHandlerMixin( eventhandlermixin.EventHandlerMixin):
    """Glut-specific EventHandlerMixin sub-class

    Adds the various callbacks for GLUT's events to
    translate them to OpenGLContext events.
    """
    ### KEYBOARD interactions
    def glutOnKeyDown( self, character, x,y ):
        '''Convert a key-press to a context-style event'''
        self.ProcessEvent( GLUTKeyboardEvent( self, character, x, y, 1, glutGetModifiers()))
    def glutOnKeyUp( self, character, x,y ):
        '''Convert a key-release to a context-style event'''
        self.ProcessEvent( GLUTKeyboardEvent( self, character, x, y, 0, glutGetModifiers()))
    def glutOnCharacter( self, character, x,y ):
        """Convert character (non-control) press to context event"""
        # need intelligence to determine what should generate a keyboard event
        # currently duplicates can occur.
        self.ProcessEvent( GLUTKeyboardEvent( self, character, x,y, 1, glutGetModifiers()))
        self.ProcessEvent( GLUTKeypressEvent( self, character, x,y, glutGetModifiers()))
    ### MOUSE Interaction
    def glutOnMouseButton(self, button, state, x, y):
        """Convert mouse-press-or-release to a Context-style event"""
        self.addPickEvent( GLUTMouseButtonEvent( self,button, state, x, y, glutGetModifiers()))
        self.triggerPick()
    def glutOnMouseMove(self, x, y):
        """Convert mouse-movement to a Context-style event"""
        self.addPickEvent( GLUTMouseMoveEvent( self, x,y))
        self.triggerPick()


class GLUTXEvent(object):
    """Base class for the various GLUT event types

    Attributes:
        CURRENTBUTTONSTATES -- three-tuple of the currently-
            known button-states for the mouse, class-static
            list
    """
    CURRENTBUTTONSTATES = [0,0,0]
    def _getModifiers( self, modifierMask):
        """Get the 3-tuple of modifier booleans"""
        return (
            not( not(GLUT_ACTIVE_SHIFT & modifierMask)),
            not( not(GLUT_ACTIVE_CTRL & modifierMask)),
            not( not(GLUT_ACTIVE_ALT & modifierMask)),
        )
    def _updateButtons( self, button, state ):
        """Update the global mouse-button-states with an event's data
        """
        if state == GLUT_UP:
            state = 0
        else:
            state = 1
        index = {
            GLUT_LEFT_BUTTON: 0,
            GLUT_RIGHT_BUTTON: 1,
            GLUT_MIDDLE_BUTTON: 2,
        }.get( button )
        if index is None:
            if button not in (3,4):
                # is a mouse-wheel button 
                log.warn( "Unrecognized button ID: %s", button, )
            return -1,state
        else:
            self.CURRENTBUTTONSTATES[index] = state
            return index, state
        

class GLUTMouseButtonEvent( GLUTXEvent, mouseevents.MouseButtonEvent ):
    """GLUT-specific mouse-button event"""
    def __init__( self, context, button, state, x, y, modifiers =0 ):
        super (GLUTMouseButtonEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.button, self.state = self._updateButtons( button, state )
        self.modifiers = self._getModifiers( modifiers )
        self.pickPoint = x , context.getViewPort()[1]- y
        
class GLUTMouseMoveEvent( GLUTXEvent, mouseevents.MouseMoveEvent ):
    """GLUT-specific mouse-move event"""
    def __init__( self, context, x,y, modifiers =0 ):
        super (GLUTMouseMoveEvent , self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        buttons = []
        for index in range( len(self.CURRENTBUTTONSTATES)):
            if self.CURRENTBUTTONSTATES[index]:
                buttons.append( index )
        self.buttons = tuple( buttons )
        self.modifiers = self._getModifiers( modifiers )
        self.pickPoint = x,context.getViewPort()[1]- y

class GLUTKeyboardEvent( GLUTXEvent, keyboardevents.KeyboardEvent ):
    """GLUT-specific keyboard event"""
    def __init__( self, context, character, x,y, state = 1, modifiers =0 ):
        super (GLUTKeyboardEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers( modifiers )
        self.name = keyboardMapping.get( character, character)	
        self.state = state
        
class GLUTKeypressEvent( GLUTXEvent, keyboardevents.KeypressEvent ):
    """GLUT-specific key-press event"""
    def __init__( self, context, character, x,y, modifiers =0 ):
        super (GLUTKeypressEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers( modifiers )
        self.name = keyboardMapping.get( character, character)	

keyboardMapping = {
    GLUT_KEY_F1: '<F1>',
    GLUT_KEY_F2: '<F2>',
    GLUT_KEY_F3: '<F3>',
    GLUT_KEY_F4: '<F4>',
    GLUT_KEY_F5: '<F5>',
    GLUT_KEY_F6: '<F6>',
    GLUT_KEY_F7: '<F7>',
    GLUT_KEY_F8: '<F8>',
    GLUT_KEY_F9: '<F9>',
    GLUT_KEY_F10: '<F10>',
    GLUT_KEY_F11: '<F11>',
    GLUT_KEY_F12: '<F12>',
    GLUT_KEY_LEFT: '<left>',
    GLUT_KEY_RIGHT: '<right>',
    GLUT_KEY_UP: '<up>',
    GLUT_KEY_DOWN: '<down>',
    GLUT_KEY_PAGE_UP: '<pageup>',
    GLUT_KEY_PAGE_DOWN: '<pagedown>',
    GLUT_KEY_HOME: '<home>',
    GLUT_KEY_END: '<end>',
    GLUT_KEY_INSERT: '<insert>',
    '\015': '<return>',
    '\011': '<tab>',
    # note the ASCII encodings
    '\033': '<escape>',
    '\177': '<delete>',
    '\010': '<backspace>',
}
buttonMapping = {
    GLUT_LEFT_BUTTON: 0,
    GLUT_RIGHT_BUTTON: 1,
    GLUT_MIDDLE_BUTTON: 2,
}
    
