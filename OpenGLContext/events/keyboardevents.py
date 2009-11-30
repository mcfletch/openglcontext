"""Event classes and manager relating to the keyboard"""
from OpenGLContext.events import event, eventmanager
    
class KeyboardEvent (event.Event):
    """Raw keyboard events, includes <ctrl> and the like.
    Characters are reported as their un-modified equivalents,
    so that 'A' represents both "a" and "A"

    attributes:
        type -- "keyboard"
        renderingPass -- pointer to the OpenGLContext.renderpass.RenderPass
            object associated with this event
        modifiers -- three-tuple of booleans: (shift, control, alt)
        name -- the "key name" see KeyboardEventManager.registerCallback
            for discussion of possible values.
        state -- Boolean 0 = up/released, 1 = down/pressed
    """
    type = "keyboard"
    name = ""
    state = 0 # 0 = up/released, 1 = down/pressed
    
    side = 0 # 1 = left, 2 = right, 3= keypad may not be available everywhere
    def getKey (self):
        """Get the event key used to lookup a handler for this event"""
        return self.name, self.state, self.getModifiers()

class KeypressEvent( event.Event ):
    """Key "pressed" event, doesn't include control characters,
    and should provide "processed" characters, so that, for
    instance, <shift>-<capslock>-A gives "a", not "A".  Note also
    that these are "full-press" events, not up/down notifications

    attributes:
        type -- "keypress"
        renderingPass -- pointer to the OpenGLContext.renderpass.RenderPass
            object associated with this event
        modifiers -- three-tuple of booleans: (shift, control, alt)
        name -- the "key name" see KeypressEventManager.registerCallback
            for discussion of possible values.
    """
    type = "keypress"
    name = ""
    side = 0 # 1 = left, 2 = right, 3= keypad may not be available everywhere
    repeating = 0 # if true, this is a virtual event generated as a typematic repeat
    def getKey (self):
        """Get the event key used to lookup a handler for this event"""
        return (self.name, self.getModifiers())

class KeyboardEventManager (eventmanager.EventManager):
    """Class responsible for registration, deregistration and processing
    of keyboard-based events.  Also can be used to track meta-key state"""
    type = KeyboardEvent.type
    def registerCallback(self, name= None, state = 0, modifiers = (0,0,0), function = None):
        """Register a function to receive keyboard events matching
        the given specification  To deregister, pass None as the
        function.

        name -- string name for the key in which you are interested
            if this is None, the entire key is None
            and will be matched only after all other names fail.
            
            Valid Values:
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
            Note: the characters are reported as their "lowercase"
            values, though the key might be known as "B" to the
            underlying system.
            
            Note: the names are always the "un-shifted" keys, that
            is, on a US keyboard, you'll never get "&" as the event
            name, you'll get "7" with the modifiers showing shift
            as being down.

        state -- key state (0 = up, 1 = down)
        function -- function taking a single argument (a KeyboardEvent)
            or None to deregister the callback.

        returns the previous handler or None
        """
        if name is not None:
            key = name, state, modifiers
        else:
            key = None
        return super( KeyboardEventManager, self).registerCallback( key, function )
class KeypressEventManager (eventmanager.EventManager):
    type = KeypressEvent.type
    def registerCallback(self, name= None, modifiers = (0,0,0), function = None):
        """Register a function to receive keyboard events matching
        the given specification  To deregister, pass None as the
        function.

        name -- string name for the key in which you are interested
            if this is None, the entire key is None
            and will be matched only after all other names fail.
            
            Valid Values:
                characters > 32 and < 256
                '<return>', '<tab>'
                '<insert>', '<delete>',
                '<up>','<down>',
                '<left>','<right>',
                '<pageup>','<pagedown>',
                '<home>','<end>',
                '<escape>',
                '<F1>' to '<F12>', to '<F24>' on some platforms
                
            Note: Attempts will be made to convert the character
            to the "real" character typed (i.e. if shift is down
            you should get 'F' instead of 'f' unless caps-lock is
            also down).  This is going to be fragile because it
            may require trying to figure it out just from the
            modifier states, and that won't work across keyboard
            types.
            
        modifiers -- (shift, control, alt) as a tuple of booleans.
        function -- function taking a single argument (a KeypressEvent)
            or None to deregister the callback.
            
        returns the previous handler or None
        """
        if name is not None:
            key = name, modifiers
        else:
            key = None
        return super( KeypressEventManager, self).registerCallback( key, function )