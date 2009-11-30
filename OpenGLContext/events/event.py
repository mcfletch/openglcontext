"""Base class for all OpenGLContext event objects."""
class Event(object):
    """Base class for all local event objects.

    This is an abstract class from which all local event objects are
    derived.  It defines the base API for each event type, as understood
    by the event dispatch system.

    Attributes:
        type -- string value representing type of event REQUIRED!
            Examples: "mousebutton", "mousemove", "keyboard", "keypress"
        renderingPass -- pointer to the OpenGLContext.renderpass.RenderPass
            object associated with this event
        modifiers -- three-tuple of booleans: (shift, control, alt)
        context -- pointer to the rendering context
    """
    type = ""
    context = None
    renderingPass = None
    modifiers = (0,0,0) # keyboard modifiers, three-tuple of shift, control, alt
    def __init__(self):
        """Initialize common event parameters"""
        self.visitedNodes = {}
    def visited (self, key, value = None):
        """Check for or register visitation of the given key

        key -- an opaque hashable value, normally the node and
            field/event as a tuple.
        value -- if provided, sets the current value, otherwise
            signals that the current value should be returned

        return value: previous key value (possibly None)
        """
        if value is None:
            self.visitedNodes.get(key)
        else:
            previousValue = self.visitedNodes.get(key)
            self.visitedNodes[key] = value
            return previousValue
    def getKey (self):
        """Calculate the key for routing within the event manager.

        Each subclass will define the appropriate data values for
        inclusion in the key (note that the key must be a hashable
        value).
        """
    def getModifiers( self ):
        """Retrieve a tuple of the active modifier keys

        Format is three Boolean values, (shift, control, alt)
        """
        return self.modifiers
    
    