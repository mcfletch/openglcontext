"""Events relating to time and timers"""
from typing import Any

from . import event

class TimeEvent( event.Event ):
    """Base class for all time-related events

    Attributes:
        discrete -- whether or not this is a discrete-time
            event, that is whether it a non-fractional event,
            defaults to true
        type -- static event type, "time"
        timetype -- a string specifying the time-event sub-type
            see subclasses in this module for valid specifiers
    """
    discrete: int = 1
    type = "time"
    timetype: str = ""
    def __init__( self, internal: Any ) -> None:
        """Initialize the TimeEvent

        internal -- pointer to the InternalTime object which
            is instantiating us.  We will store a reference
            to the internal time as well as caching various
            values specific to this event.
        """
        super (TimeEvent, self).__init__()
        self.__internal: Any = internal
        self.__value: float = self.__internal.getCurrent()
        self.__external: Any = self.__internal.getExternal()
        self.__count: int = self.__internal.count
        #: The Timer that dispatches this event, once it has said so.
        self.__timer: Any = None
    def __repr__( self ) -> str:
        """Present a meaningful representation of the event"""
        return """<%s value=%s fraction=%s external=%s count=%s>"""% (
            self.__class__.__name__,
            self.value (),
            self.fraction (),
            self.external (),
            self.count (),
        )
        
    def setTimer( self, timer: Any ) -> None:
        """Set (opaque) pointer to a Timer object

        This method allows higher-level timer abstractions
        to store a pointer to their implementations to allow
        higher-level operation.
        """
        self.__timer = timer
    def getTimer( self ) -> Any:
        """Get (opaque) pointer to Timer object

        This method allows higher-level timer abstractions
        to store a pointer to their implementations to allow
        higher-level operation.
        """
        return self.__timer
    
    def getKey( self ) -> str:
        """Event API: get the general event type (self.timetype)"""
        return self.timetype
    def value( self ) -> float:
        """Get the internal time at instantiation"""
        return self.__value
    def fraction( self ) -> float:
        """Get the fractional time at instantiation"""
        return self.value()/self.duration()
    def external( self ) -> Any:
        """Get the external time at instantiation"""
        return self.__external
    def duration( self ) -> float:
        """Get the total internal-time cycle duration"""
        duration: float = self.__internal.duration
        return duration
    def count( self ) -> int:
        """Get the internal-time cycle count at instantiation"""
        return self.__count
    
    
class StartEvent( TimeEvent ):
    """Event generated when the internal time is started

    This event is generated:
        when InternalTime.start is called
    """
    timetype = "start"
class ResumeEvent( TimeEvent ):
    """Event generated when the internal time is resumed

    This event is generated:
        * when InternalTime.resume is called
    """
    timetype = "resume"
class StopEvent( TimeEvent ):
    """Event generated when the internal time stops

    This event is generated:
        * when InternalTime.stop is called
        * when a non-repeating InternalTime reaches
            the end of the cycle (natural finish)
        * when a repeating, but count-limited
            InternalTime reaches the end of its last
            cycle.
            
    If the InternalTime generates fractional events,
    then a fractional event will be generated at the
    same time as the StopEvent
    """
    timetype = "stop"
class PauseEvent( TimeEvent ):
    """Event generated when the internal time is paused

    This event is generated:
        * when InternalTime.pause is called
    """
    timetype = "pause"
class CycleEvent( TimeEvent ):
    """Event generated when the internal time reaches cycle boundary

    This event is generated:
        * when an InternalTime reaches a cycle boundary
            which does not cause a StopEvent (i.e. when
            the InternalTime continues past a cycle
            boundary)

    If the InternalTime generates fractional events,
    then a fractional event will be generated at the
    same time as the CycleEvent
    """
    timetype = "cycle"
class FractionalEvent( TimeEvent ):
    """Event generated when the InternalTime changes time fraction

    FractionalEvents are only generated when the
    InternalTime's discreteOnly attribute is false.

    This event is generated:
        * when InternalTime.poll is called
        * when InternalTime.stop is called

    Note:
        This is the only non-discrete event at the moment
    """
    timetype = "fraction"
    discrete = 0
