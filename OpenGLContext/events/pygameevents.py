"""Module providing translation from pygame events to OpenGLContext events"""
from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
import pygame, string
from pygame.locals import *
import logging 
log = logging.getLogger( __name__ )

class EventHandlerMixin( eventhandlermixin.EventHandlerMixin):
    """Pygame-specific EventHandlerMixin

    Provides mappings from Pygame events to the equivalent
    Context event classes.
    """
    ### KEYBOARD interactions
    def PygameKeyDown( self, event ):
        '''Convert a key-press to a context-style event'''
        self.ProcessEvent( PygameKeyboardEvent( self, event, 1))
        # hack, needs work!
        if event.unicode:
            self.ProcessEvent( PygameKeypressEvent( self, event))
        return 1
    def PygameKeyUp( self, event ):
        '''Convert a key-release to a context-style event'''
        self.ProcessEvent( PygameKeyboardEvent( self, event, 0))
        return 1
    ### MOUSE Interaction
    def PygameMouseButtonUp(self, event ):
        """Convert a mouse-button-release to a context-style event"""
        self.addPickEvent( PygameMouseButtonEvent( self, event, state = 0))
        self.triggerPick()
        return 1
    def PygameMouseButtonDown(self, event ):
        """Convert a mouse-button-press to a context-style event"""
        self.addPickEvent( PygameMouseButtonEvent( self, event, state = 1))
        self.triggerPick()
        return 1
    def PygameMouseMotion(self, event ):
        """Convert a mouse-button-move to a context-style event"""
        self.addPickEvent( PygameMouseMoveEvent( self, event))
        self.triggerPick()
        return 1

class PygameXEvent(object):
    """Base class for all Pygame-specific event types

    Provides functions for determining the modifier state,
    and for translating key names between the two standards

    Attributes:
        CURRENTBUTTONSTATES -- tracks the current state of the
            mouse buttons, a three-value list
    """
    CURRENTBUTTONSTATES = [0,0,0]
    def _getModifiers(self):
        "get the state of the keyboard modifiers"
        mods = pygame.key.get_mods()
        return (
            not(not(mods & KMOD_SHIFT)),
            not(not(mods & KMOD_CTRL)),
            not(not(mods & KMOD_ALT)),
        )

    def _translateKey(self, name):
        "Translate a key from pygame to interactivecontext"
        if len(name) > 1:
            if name[0] == '[':
                name = '#' + name[1]
            if name not in ( 'left', 'right'):
                name = name.replace('left', '')
                name = name.replace('right', '')
            name = name.replace(' ', '')
            name = '<' + name + '>'
            if '<f1>' <= name <= '<f15>':
                name = name.upper()
        return name
    def _updateButtons( self, button, state ):
        """Update the tracked state for mouse buttons

        pygame is 1+ context button IDs
        """
        for local, pg in ( (0,1), (1,3), (2,2)):
            if button == pg:
                self.CURRENTBUTTONSTATES[local] = state
                return local
        log.warn(
            """Unrecognised button: %s""", button,
        )
        return button-1

class PygameMouseButtonEvent( PygameXEvent, mouseevents.MouseButtonEvent ):
    """Pygame-specific mouse-button state change event"""
    def __init__( self, context, PygameEventObject, state= 0 ):
        super (PygameMouseButtonEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        self.state = state
        # is this right?
        self.button = self._updateButtons( PygameEventObject.button, state )
        relx, rely = PygameEventObject.pos
        self.pickPoint = relx, context.getViewPort()[1]- rely
        
class PygameMouseMoveEvent( PygameXEvent, mouseevents.MouseMoveEvent ):
    """Pygame-specific mouse-movement event"""
    def __init__( self, context, PygameEventObject ):
        super (PygameMouseMoveEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        buttons = []
        for index in range( len(self.CURRENTBUTTONSTATES)):
            if self.CURRENTBUTTONSTATES[index]:
                buttons.append( index )
        self.buttons = tuple( buttons )
        relx, rely = PygameEventObject.pos
        self.pickPoint = relx, context.getViewPort()[1]- rely

class PygameKeyboardEvent( PygameXEvent, keyboardevents.KeyboardEvent ):
    """Pygame-specific keyboard (character) event"""
    def __init__( self, context, PygameEventObject, state=0 ):
        super (PygameKeyboardEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        self.name = self._translateKey( pygame.key.name(PygameEventObject.key) )
        self.state = state
        
class PygameKeypressEvent( PygameXEvent, keyboardevents.KeypressEvent ):
    """Pygame-specific key-press (or release) event"""
    def __init__( self, context, PygameEventObject):
        super (PygameKeypressEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers()
        # note: this is wrong, should translate according to modifiers etceteras...
        self.name = self._translateKey( PygameEventObject.unicode)
