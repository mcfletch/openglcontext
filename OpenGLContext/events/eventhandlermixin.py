"""Mix in functionality for Context classes needing event support"""

try:
    import Queue
except ImportError:
    import queue as Queue
import logging
import time

from OpenGL._bytes import as_str

log = logging.getLogger(__name__)


class HeldKeyMixin(object):
    """Which keys are down, and what a platform does not tell us about them

    Two things every backend needs and none of them gets from the window
    system alone:

    **A key that was down when the window lost focus never comes up.**  No
    platform sends the release, so anything reading held keys -- navigation
    above all -- has the key held for the rest of the session, and the camera
    keeps moving with nobody touching the keyboard.  :meth:`clearHeldKeys`
    sends the releases the window system did not.

    **Some platforms deliver no key-repeat.**  A held key then arrives as one
    press and nothing else, which breaks held-key navigation on backends whose
    movement is driven by repeats.  :meth:`pumpKeyRepeats`, called once per
    loop iteration, supplies them -- and stops the moment
    :meth:`noteNativeRepeat` says the platform delivers its own, so a platform
    that repeats is never doubled.

    A backend mixes this in and implements :meth:`emitKey`; what a key is
    called is the backend's own business, since this only ever hands back what
    it was given.
    """

    #: Seconds a key is held before the first synthetic repeat.
    keyRepeatDelay = 0.4
    #: Seconds between synthetic repeats after that (about twenty a second).
    keyRepeatInterval = 0.05

    _nativeRepeat = False

    def emitKey(self, key, state, modifiers):
        """Send one key transition to the engine

        Implemented by the backend, which is what knows how to build its own
        event class.
        """
        raise NotImplementedError(
            '%s must implement emitKey to use held-key tracking'
            % (self.__class__.__name__,))

    def heldKeys(self):
        """The keys currently down, as ``{key: modifiers}``"""
        return dict((key, held[0]) for key, held in self._heldMap().items())

    def noteKeyDown(self, key, modifiers, now=None):
        """Record that ``key`` went down, and when its first repeat is due"""
        when = time.time() if now is None else now
        self._heldMap()[key] = [modifiers, when + self.keyRepeatDelay]

    def noteKeyUp(self, key):
        """Record that ``key`` came up"""
        self._heldMap().pop(key, None)

    def noteNativeRepeat(self):
        """The platform delivers its own key-repeat; stop supplying one"""
        self._nativeRepeat = True

    def pumpKeyRepeats(self, now=None):
        """Emit a repeat for every held key that is due one

        Called once per main-loop iteration.  A no-op once native repeat has
        been seen, and when nothing is held.
        """
        held = self.__dict__.get('_heldKeysMap')
        if self._nativeRepeat or not held:
            return
        when = time.time() if now is None else now
        for key, info in list(held.items()):
            if when >= info[1]:
                self.emitKey(key, 1, info[0])
                info[1] = when + self.keyRepeatInterval

    def clearHeldKeys(self):
        """Let go of every held key, as though each had been released

        For focus loss, where no release arrives from the platform.  An
        application that tracks held keys itself only ever learns a key came up
        from the event, so dropping the map without sending one leaves the key
        down for ever on its side.
        """
        held = self.__dict__.pop('_heldKeysMap', None) or {}
        for key, info in held.items():
            self.emitKey(key, 0, info[0])

    def _heldMap(self):
        held = self.__dict__.get('_heldKeysMap')
        if held is None:
            held = self.__dict__['_heldKeysMap'] = {}
        return held


class EventHandlerMixin(HeldKeyMixin):
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

    def initializeEventManagers(self):
        """Initialize the event manager classes for this context.

        This implementation iterates over self.EventManagerClasses
        (a list of (eventType, managerClass) values) and calls
        addEventManager for each item.
        """
        self.__managers = {}
        self.__uncaptureDict = {}
        for key, managerClass in self.EventManagerClasses:
            self.addEventManager(key, managerClass())
        if self.TimeManagerClass:
            self.__timeManager = self.TimeManagerClass()
        else:
            self.__timeManager = None

    ### Client API
    def addEventHandler(self, eventType, *arguments, **namedarguments):
        """Add a new event handler function for the given event type

        This is the primary client API for dealing with the event system.
        Each event class will define a particular set of data values
        required to form the routing key for the event.  Each event handler
        class will define a registerCallback function which converts
        its arguments into a matching key.

        This function merely determines the appropriate handler then
        dispatches to the handler's registerCallback method (without the
        eventType argument).

        **The caller owns the callback and must keep it alive.** Handlers are
        held by *weak* reference, so a callback with no other reference to it is
        collected as soon as this call returns, and the binding then does nothing
        at all -- the key or button is silently dead, with no error raised here
        or at dispatch time.  This is deliberate: it is what lets a node or
        context be garbage collected without first unbinding every handler it
        registered.

        Pass something that outlives the binding.  A bound method of a live
        object is the normal choice, and is what every example below uses::

            self.addEventHandler( 'keyboard', name='<up>', state=1,
                                  function=self.forward )

        A bare closure, a lambda, a functools.partial, or any other object
        created purely for the call will *not* survive it.  If you need one,
        store it somewhere that lives as long as the binding should::

            self.handlers = []            # an attribute of a long-lived object
            handler = lambda event: self.step( +1 )
            self.handlers.append( handler )
            self.addEventHandler( 'keyboard', name='w', state=1,
                                  function=handler )

        Passing function=None deregisters instead, and returns the previous
        callback.

        See: mouseevents, keyboardevents
        """
        manager = self.getEventManager(as_str(eventType))
        if manager:
            manager.registerCallback(*arguments, **namedarguments)
        else:
            raise KeyError("""Unrecognised EventManager type %s""" % (repr(eventType)))

    def captureEvents(self, eventType, manager=None):
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
        eventType = as_str(eventType)
        if manager:
            previous = self.addEventManager(eventType, manager)
            self.__uncaptureDict[eventType] = previous
        else:
            previous = self.__uncaptureDict.get(eventType)
            self.addEventManager(eventType, previous)
            if previous:
                del self.__uncaptureDict[eventType]

    def isCapturingEvents(self, eventType):
        """Whether a manager has taken this event type over for the moment.

        A capture is how a drag receives its own events -- it swaps itself into
        the slot rather than registering with the dispatcher -- so asking the
        dispatcher whether anyone is listening answers "no" for exactly the
        interaction that most needs the events.  Anything optimising delivery
        away has to ask this as well.
        """
        return as_str(eventType) in self.__uncaptureDict

    ### Customisation points
    def ProcessEvent(self, event):
        """Primary dispatch point for events.

        ProcessEvent uses the event's type attribute to determine the
        appropriate manager for processing, then dispatches to that manager's
        ProcessEvent method."""
        manager = self.getEventManager(event.type) or self.getEventManager(None)
        if manager:
            event.context = self
            if self.drawing:
                self.eventCascadeQueue.put((manager.ProcessEvent, (event,), {}))
            else:
                return manager.ProcessEvent(event)
        else:
            if __debug__:
                log.warning(
                    """Unrecognised event type %s received by context event: %r""",
                    event.type,
                    event,
                )
        return None

    ### Internal API
    def addEventManager(self, eventType, manager=None):
        """Add an event manager to the internal table of managers.

        The return value is the previous manager or None if there was
        no previous manager.
        """
        returnValue = self.__managers.get(eventType)
        self.__managers[eventType] = manager
        return returnValue

    def getEventManager(self, eventType):
        """Retrieve an event manager from the internal table of managers

        Returns the appropriate manager, or None if there was no
        manager registered for the given event type.
        """
        return self.__managers.get(eventType)

    def DoEventCascade(
        self,
    ):
        """Do pre-rendering event cascade

        Returns the total number of events generated by
        timesensors and/or processed from the event cascade queue
        """
        events = 0
        if self.__timeManager:
            events = events + self.__timeManager(self)
            if events:
                # time-sensors have generated events, need to redraw scene
                self.triggerRedraw(0)
        while not self.drawing:
            # should never change during regular use, but it's
            # easy to track...
            try:
                func, args, named = self.eventCascadeQueue.get(0)
                func(*args, **named)
                events = events + 1
            except Queue.Empty:
                break
        return events

    def getTimeManager(self):
        """Get the time-event manager for this context"""
        return self.__timeManager
