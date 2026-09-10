"""Base class for all OpenGLContext event objects."""
from typing import Any, Dict, Optional, Tuple


class Event(object):
    """Base class for all local event objects.

    This is an abstract class from which all local event objects are
    derived.  It defines the base API for each event type, as understood
    by the event dispatch system.

    Attributes:
        type -- string value representing type of event REQUIRED!
            Examples: "mousebutton", "mousemove", "keyboard", "keypress"
        renderingPass -- the FlatPass (passes/_flat.py) rendering this
            frame, or None outside a render pass
        modifiers -- three-tuple of booleans: (shift, control, alt)
        context -- pointer to the rendering context
    """
    type: str = ""
    context: Any = None
    renderingPass: Any = None
    #: keyboard modifiers, three-tuple of shift, control, alt
    modifiers: Tuple[int, int, int] = (0, 0, 0)

    def __init__(self) -> None:
        """Initialize common event parameters"""
        self.visitedNodes: Dict[Any, Any] = {}

    def visited(self, key: Any, value: Optional[Any] = None) -> Optional[Any]:
        """Check for or register visitation of the given key

        key -- an opaque hashable value, normally the node and
            field/event as a tuple.
        value -- if provided, sets the current value, otherwise
            signals that the current value should be returned

        return value: previous key value (possibly None)

        This is what stops an event going round a cycle of ROUTEs for ever:
        the router asks whether a destination has already been reached on this
        event and gives up when it has (``vrml.route.ROUTE._forward``).
        """
        if value is None:
            return self.visitedNodes.get(key)
        previousValue = self.visitedNodes.get(key)
        self.visitedNodes[key] = value
        return previousValue

    def getKey(self) -> Any:
        """Calculate the key for routing within the event manager.

        Each subclass will define the appropriate data values for
        inclusion in the key (note that the key must be a hashable
        value).
        """

    def getPickKey(self) -> Any:
        """Calculate the key that makes this event distinct within one frame.

        A context holds pending pick events in a mapping under this key (see
        Context.addPickEvent), so two events sharing one are the same question
        asked twice and only the later is answered.  That is what is wanted of
        a click or a movement, where the current state is the whole of the
        news; an event that instead carries an *increment* overrides this so
        that none of them is dropped.
        """
        return self.getKey()

    def getModifiers(self) -> Tuple[int, int, int]:
        """Retrieve a tuple of the active modifier keys

        Format is three Boolean values, (shift, control, alt)
        """
        return self.modifiers
