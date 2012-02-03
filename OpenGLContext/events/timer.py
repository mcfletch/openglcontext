"""EventManager providing vcr-like control of an InternalTime object"""
import eventmanager, systemtime, internaltime
from pydispatch import dispatcher
import logging 
log = logging.getLogger( __name__ )

class Timer( eventmanager.EventManager ):
    """Event manager providing VCR-like control of an InternalTime

    Timer objects are currently the only end-user friendly
    timing mechanism available within OpenGLContext.  They
    provide simple VCR-like control of an InternalTime.

    This allows the Timer to run forward, backward, fast,
    slow, pause, or resume.  The class allows you to register
    for events (fractional, cyclic or one-shot) as normal
    for eventmanager classes.

    Attributes:
        timerClass -- the class of InternalTime object used
        active -- Boolean flag indicating whether we are
            "active", that is, whether we are currently
            advancing through the internal time.
        internal -- the instantiated InternalTime object we
            are using to implement ourselves
    """
    timerClass = internaltime.InternalTime
    def __init__(
        self, *arguments, **namedarguments
    ):
        """Initialize the Timer

        arguments, namedarguments -- passed directly to
            our timerClass to instantiate the InternalTime.
            See documentation on InternalTime  for details.
        """
        self.internal = self.timerClass(*arguments, **namedarguments )
        eventmanager.EventManager.__init__ (self)
    def __repr__( self ):
        """Get an useful representation of the Timer"""
        return """<%s %s>"""%( self.__class__.__name__, self.internal )
    @property
    def active( self ):
        """Delegate to internal"""
        return self.internal.active
    def register (self, context):
        """Register this timer with a given context's time event manager

        See:
            timeeventgeneratormanager.TimeEventGeneratorManager
        """
        if hasattr( context, "getTimeManager"):
            if context.getTimeManager():
                context.getTimeManager().addEventGenerator(self)
            else:
                raise ValueError ("""Attempted to register a Timer for a Context with a NULL getTimeManager() result"""% (context))
        else:
            raise ValueError ("""Attempted to register a Timer for a Context %s without a getTimeManager method"""% (context))
        
    def deregister (self, context):
        """De-register this timer with a given context's time event manager

        See:
            timeeventgeneratormanager.TimeEventGeneratorManager
        """
        if hasattr( context, "getTimeManager"):
            if context.getTimeManager():
                context.getTimeManager().removeEventGenerator(self)
            else:
                raise ValueError ("""Attempted to de-register a Timer for a Context with a NULL getTimeManager() result"""% (context))
        else:
            raise ValueError ("""Attempted to de-register a Timer for a Context %s without a getTimeManager method"""% (context))
    def addEventHandler( self, timetype ="fraction", function = None ):
        """Add/remove handler for the given timetype from this Timer object

        timetype -- string value describing the event type, currently
            valid types are:
                "start"
                "stop"
                "resume"
                "pause"
                "cycle"
                "fraction"
            see the timeevents module for description of the individual
            types.
        function -- callback function taking single argument, a
            Context time event
        """
        return super( Timer, self).registerCallback(
            timetype,
            function = function,
            node = self,
        )
    def ProcessEvent(self, event):
        """Dispatch an incoming event

        This sub-class sets the Timer as the sender of the
        messages.
        """
        processed = 0
        # anonymous mouse function only...
        metaKey = (self.type,0,event.getKey())
        # the sender is this Timer object
        results = dispatcher.sendExact( metaKey, self, event )
        for handler, result in results:
            if __debug__:
                log.debug( '   handler %s -> %r', handler, result )
            processed = processed or result
        return processed

    def _doAndDispatch (self, function, realTime, *arguments,**namedarguments):
        """Internal function to get and dispatch events from internal function

        function -- the internaltime method which will generate the events
        realTime -- external time passed to the internal time, if absent
            will use systemtime.systemTime()
        arguments, namedarguments -- passed to the function after realTime
        """
        if realTime is None:
            realTime = systemtime.systemTime()
        events = function(realTime, *arguments, **namedarguments)
        for event in events:
            event.setTimer( self )
            self.ProcessEvent( event )
        return len(events)
        
    def poll( self, realTime = None ):
        """Poll the internal timer for pending events

        Returns the number of events dispatched
        """
        return self._doAndDispatch(self.internal.poll, realTime)
        
    def start (self, realTime = None):
        """Start the internal timer"""
        self._doAndDispatch(self.internal.start, realTime)
    def stop(self, realTime = None):
        """Stop the internal timer"""
        self._doAndDispatch(self.internal.stop, realTime)
    def pause (self, realTime = None):
        """Pause the internal timer"""
        self._doAndDispatch(self.internal.pause, realTime)
    def resume(self, realTime = None):
        """Resume the internal timer"""
        self._doAndDispatch(self.internal.resume, realTime)
        
if __name__ == "__main__":
    def test ():
        cases = [
            Timer (duration = 10, repeating = -1),
            Timer (duration = 10, repeating = 2),
            Timer (duration = 10, repeating = 0, multiplier = .5),
            Timer (duration = 10, repeating = 1, multiplier = -1),
            Timer (duration = 2, repeating = 1, discreteOnly=1),
        ]
        for case in cases:
            print case
            def printer (event):
                print event
            case.addEventHandler ("fraction",printer)
            case.addEventHandler ("start",printer)
            case.addEventHandler ("stop",printer)
            case.addEventHandler ("cycle",printer)
            case.addEventHandler ("pause",printer)
            case.addEventHandler ("resume",printer)
            case.start (0)
            for integer in range(31):
                case.poll(float (integer))
            case.stop (32.0)
    test ()
