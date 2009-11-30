"""Module providing translation from FxPy events to OpenGLContext events [unfinished]"""

from OpenGLContext.events import mouseevents, keyboardevents, eventhandlermixin
from FXPy.fox import *
import time

class EventHandlerMixin( eventhandlermixin.EventHandlerMixin):
    ### KEYBOARD interactions
    def fxOnKeyDown( self, event ):
        '''Convert a key-press to a context-style event'''
        print 'key down', event
        return
        self.ProcessEvent( fxKeyboardEvent( self, event, 1))
    def fxOnKeyUp( self, event ):
        '''Convert a key-press to a context-style event'''
        print 'key up', event
        return
        self.ProcessEvent( fxKeyboardEvent( self, event, 0))
    def fxOnCharacter( self, event ):
        """Convert character (non-control) press to context event"""
        print 'character', event
        return
        self.ProcessEvent( fxKeypressEvent( self, event))
    ### MOUSE Interaction
    def fxOnMouseButton(self, canvas, ID, event):
        print 'mouse button', event
        return
        self.addPickEvent( fxMouseButtonEvent( self, event))
        self.triggerPick()
    def fxOnMouseMove(self, canvas, ID, event):
        self.addPickEvent( fxMouseMoveEvent( self, event))
        self.triggerPick()

class fxXEvent:
    def _getModifiers( self, fxEventObject):
        return (
            not(not( fxEventObject.ShiftDown())),
            not(not( fxEventObject.ControlDown())),
            not(not( fxEventObject.AltDown())),
        )

class fxMouseButtonEvent( fxXEvent, mouseevents.MouseButtonEvent ):
    def __init__( self, context, fxEventObject ):
        super (fxMouseButtonEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(fxEventObject)
##		import pdb
##		pdb.set_trace()
        for local, fx in ( (0,1), (1,3), (2,2)):
            if fxEventObject.Button( fx ):
                self.button = local
                self.state = fxEventObject.ButtonDown()
                break
        self.pickPoint = fxEventObject.GetX(), context.getViewPort()[1]- fxEventObject.GetY()
        
class fxMouseMoveEvent( fxXEvent, mouseevents.MouseMoveEvent ):
    def __init__( self, context, fxEventObject ):
        super (fxMouseMoveEvent, self).__init__()
##		import pdb
##		pdb.set_trace()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
##		self.modifiers = self._getModifiers(fxEventObject)
        buttons = []
##		for local, method in ( (0,"LeftIsDown"), (1,"MiddleIsDown"), (2,"RightIsDown")):
##			if getattr( fxEventObject, method )():
##				buttons.append( local )
        self.buttons = tuple( buttons )
        self.pickPoint = fxEventObject.win_x, context.getViewPort()[1] - fxEventObject.win_y
        print 'pickPoint', self.pickPoint, context.getViewPort()

class fxKeyboardEvent( fxXEvent, keyboardevents.KeyboardEvent ):
    def __init__( self, context, fxEventObject, state=0 ):
        super (fxKeyboardEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(fxEventObject)
        self.name = keyboardMapping.get( fxEventObject.GetKeyCode())	
        self.state = state
        
class fxKeypressEvent( fxXEvent, keyboardevents.KeypressEvent ):
    def __init__( self, context, fxEventObject):
        super (fxKeypressEvent, self).__init__()
        if hasattr( context, 'currentPass'):
            self.renderingPass = context.currentPass
        self.modifiers = self._getModifiers(fxEventObject)
        self.name = keyboardMapping.get( fxEventObject.GetKeyCode())	

    