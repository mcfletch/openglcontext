"""Mix in functionality for Context classes needing event support"""
import Queue
import logging 
log = logging.getLogger( __name__ )

class EventHandlerMixin(object):
    """This class provides mix in functionality for contexts
    needing event support.

    Contexts wishing to support particular types of event will
    store pointers to each of the appropriate manager classes in
    their EventManagerClasses attribute before calling the
    EventHandlerMixin.initializeEventManagers() method. The format
    for EventManagerClasses is [ ("eventType", managerClass), ... ].

    Clients wishing to register particular event handlers will use
    addEventHandler method to register each event handler.

    Clients wishing to capture all events of a particular type for
    a limited duration will use the captureEvents method, passing
    in a pointer to an event manager which will handle the updates.
    
    The event handler mix in provides a client API for the registration
    and handling of events.
    """
    EventManagerClasses = []
    TimeManagerClass = None
    def initializeEventManagers( self ):
        """Initialize the event manager classes for this context.
        
        This implementation iterates over self.EventManagerClasses
        (a list of (eventType, managerClass) values) and calls
        addEventManager for each item.
        """
        self.__managers = {}
        self.__uncaptureDict = {}
        for key, managerClass in self.EventManagerClasses:
            self.addEventManager( key, managerClass() )
        if self.TimeManagerClass:
            self.__timeManager = self.TimeManagerClass( )
        else:
            self.__timeManager = None
    ### Client API
    def addEventHandler( self, eventType, *arguments, **namedarguments ):
        """Add a new event handler function for the given event type

        This is the primary client API for dealing with the event system.
        Each event class will define a particular set of data values
        required to form the routing key for the event.  Each event handler
        class will define a registerCallback function which converts
        its arguments into a matching key.

        This function merely determines the appropriate handler then
        dispatches to the handler's registerCallback method (without the
        eventType argument).

        See: mouseevents, keyboardevents
        """
        manager = self.getEventManager( eventType )
        if manager:
            manager.registerCallback( *arguments, **namedarguments )
        else:
            raise KeyError( """Unrecognised EventManager type %s"""%( repr(eventType)))
    def captureEvents( self, eventType, manager=None ):
        """Temporarily capture events of a particular type.

        This temporarily replaces a particular manager within the
        dispatch set with provided manager.  This will normally be
        used to create "modal" interfaces such as active drag
        functions (where the interface is in a different "interaction
        mode", so that actions have different meaning than in the
        "default mode").

        Passing None as the manager will restore the previous manager
        to functioning.

        Note: this function does not perform a "system capture"
        of input (that is, mouse movements are only available if they
        occur over the context's window and that window has focus).

        Note: for capturing mouse input, you will likely want to
        capture both movement and button events, it should be possible
        to define a single handler to deal with both event types,
        and pass that handler twice, once for each event type.
        """
        if manager:
            previous = self.addEventManager( eventType, manager )
            self.__uncaptureDict[ eventType ] = previous
        else:
            previous = self.__uncaptureDict.get( eventType )
            self.addEventManager( eventType,  previous)
            if previous:
                del self.__uncaptureDict[ eventType ]
            
    ### Customisation points
    def ProcessEvent( self, event ):
        """Primary dispatch point for events.

        ProcessEvent uses the event's type attribute to determine the
        appropriate manager for processing, then dispatches to that manager's
        ProcessEvent method."""
        manager = self.getEventManager( event.type ) or self.getEventManager( None )
        if manager:
            event.context = self
            if self.drawing:
                self.eventCascadeQueue.put( (manager.ProcessEvent, (event,), {}) )
            else:
                return manager.ProcessEvent( event )
        else:
            if __debug__:
                log.warn( """Unrecognised event type %s received by context event: %r""", event.type, event)
        return None
    
    ### Internal API
    def addEventManager( self, eventType, manager= None ):
        """Add an event manager to the internal table of managers.
        
        The return value is the previous manager or None if there was
        no previous manager.
        """
        returnValue = self.__managers.get( eventType )
        self.__managers[ eventType ] = manager
        return returnValue
    def getEventManager( self, eventType ):
        """Retrieve an event manager from the internal table of managers
        
        Returns the appropriate manager, or None if there was no
        manager registered for the given event type.
        """
        return self.__managers.get( eventType )
    def DoEventCascade(self,):
        """Do pre-rendering event cascade

        Returns the total number of events generated by
        timesensors and/or processed from the event cascade queue
        """
        events = 0
        if self.__timeManager:
            events = events + self.__timeManager( self )
            if events:
                # time-sensors have generated events, need to redraw scene
                self.triggerRedraw( 0 )
        while not self.drawing:
            # should never change during regular use, but it's
            # easy to track...
            try:
                func, args, named = self.eventCascadeQueue.get( 0 )
                func( *args, **named )
                events = events + 1
            except Queue.Empty:
                break
        return events
    def getTimeManager( self ):
        """Get the time-event manager for this context"""
        return self.__timeManager

    
