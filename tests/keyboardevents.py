#! /usr/bin/env python
'''=Keyboard Event Handling=

For any sort of interactive world, you likely want to be able to handle
keyboard events. There are two types of keyboard events in OpenGLContext,
`keypress` and `keyboard`.

Keyboard events are the low-level events. They deliver the key-code of the
base key, along with a modifier-set (shift,ctrl,alt) which tells you whether
those modifier keys are active. Normally if you want to design a navigation
mode you want to use these, as they allow you to watch for key-chords
(having multiple keys pressed at once) and let you handle repetition and
the like yourself.

Keypress events are the "interpreted" events. They are basically a post-
processed version of the keyboard event that tries to interpret what 
character the user was trying to type. They are more useful for cases
where you want to provide a text chat or settings editor.
'''
from typing import Any
'''Get a basic 3D context and a sceneGraph node.'''
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.scenegraph.basenodes import sceneGraph
'''We'll use the Heads Up Display (HUD) to show the events as they
are received.'''
from OpenGLContext.ui.hudwidgets import HUDLayer, TextBlock

class TestContext( BaseContext ):
    def OnInit( self ) -> None:
        """Scene set up and initial processing"""
        BaseContext.OnInit( self )
        '''Event handlers in OpenGLContext are registered on the context,
        under the covers this is forwarded to the EventHandler class that
        is registered for the type of event (`keypress` and `keyboard` here).
        That handler then arranges with the underlying GUI library to 
        deliver (and translate) the low-level event into the same format
        for all GUIs.

        Normally you would register for a *single* key-name, such as 'm'
        and send the handler to a piece of code that is *only* for processing
        that one key's press, but here we are using None to mean
        "don't restrict to any named key". Key names are always the
        base key value, not the shifted or composed version of the key.

        Key names::

            characters > 32 and < 256
            '<return>', '<tab>'
            '<insert>', '<delete>',
            '<up>','<down>',
            '<left>','<right>',
            '<pageup>','<pagedown>',
            '<home>','<end>',
            '<escape>', '<start>',
            '<numlock>', '<scroll>', '<capslock>',
            '<F1>' to '<F12>', to '<F24>' on some platforms
            '<shift>',
            '<ctrl>',
            '<alt>'
        '''
        self.addEventHandler(
            'keypress', name=None, function = self.OnKeyPress
        )
        self.addEventHandler(
            'keyboard', name=None, function = self.OnKeyBoard
        )
        '''Here we set up the HUD to show the formatted text describing
        the events. The TextBlock is a formatted block of 2D text which
        is anchored in the corner.'''
        self.keypressText = TextBlock(
            lines = ['Keypress events', 'strike keys to see them'],
            anchor = 'top-left',
        )
        self.keyboardText = TextBlock(
            lines = ['Keyboard events'],
            anchor = 'bottom-left',
        )
        '''Now we register the HUD layer with the context so that it will
        be rendered on every frame.'''
        self.addHUDLayer( HUDLayer( children = [
            self.keypressText,
            self.keyboardText,
        ] ) )
        '''Give the scene an empty scenegraph.'''
        self.sg = sceneGraph(
            children = [
            ]
        )
    def OnKeyBoard( self, event: Any = None ) -> bool:
        """Show the key's name, direction and modifiers"""
        '''Because the modifier keys are *also* keys, if we didn't filter
        them out, then you could never see the keys that are being modified.'''
        if event.name in ('<shift>','<alt>','<ctrl>'):
            return False
        '''Show the class of event; each GUI has a different adapter class,
        so if you are using a GLFW GUI you'll see GLFWKeyboardEvent.'''
        self.keyboardText.lines = [
            event.__class__.__name__,
            repr(event.name),
            '%s (%s)'%( ['Up','Down'][event.state], event.state),
            str( event.getModifiers()),
        ]
        self.triggerRedraw( 1 )
        return True
    def OnKeyPress( self, event: Any = None ) -> bool:
        """Show the character, its side and whether it is repeating"""
        if event.name in ('<shift>','<alt>','<ctrl>'):
            return False
        '''Some GUIs provide "side" information for a modifier, such as Right-Alt,
        rather than just Alt. Others do not. Don't rely on the Side when you are
        designing your UI if you want it to be portable across GUI systems.'''
        self.keypressText.lines = [
            event.__class__.__name__,
            repr(event.name),
            'Side: %s (%s)'%( ['Unknown','Left',"Right","Keypad"][event.side],event.side),
            'Repeating: %s (%s)'%( ['No','Yes'][event.repeating],event.repeating ),
            str( event.getModifiers()),
        ]
        self.triggerRedraw( 1 )
        return True


if __name__ == "__main__":
    TestContext.ContextMainLoop()
