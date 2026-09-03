"""Abstract base class for all event managers."""
from pydispatch import dispatcher
import logging 
log = logging.getLogger( __name__ )

class EventManager(object):
    """Abstract base class for all event managers.

    Event managers are responsible for dispatching events
    of a particular type to registered handling functions
    in response to dispatches from the Context's ProcessEvent
    method.

    This class is primarily of interest to those wishing to
    create new event classes or "capture" event managers.
    It is necessary to define a new EventManager class
    for each event type to be handled.

    For new event classes, the primary point of interest is the
    registerCallback function, which needs to be defined so
    that clients can define new keys for dispatching.

    For capture event managers (managers which are responsible
    for "modal" operation), overriding the ProcessEvent
    method is likely the most appropriate approach.
    """
    type = ""
    def __init__ (self ):
        """Initialise the event manager"""
        self.mapping = {
        }
    def hasReceivers( self ):
        """Whether any live callback is registered for this manager's event type.

        Encapsulates the pydispatch lookup here, in the events layer, so callers
        (e.g. Context.hasMouseMoveHandlers) query the relevant managers rather than
        walking the global dispatcher registry inline. Callbacks are
        registered under a ``(type, capture, key)`` signal, so a live receiver for
        this manager is any connection whose signal starts with ``self.type``.
        (``dispatcher.getAllReceivers()`` with no arguments only returns the
        register-for-Any receivers, so it cannot answer this -- hence the scan of
        the connection table.)

        **Over a snapshot, because the table is not ours to hold still.**
        pydispatch keys ``connections`` by sender and drops a sender's row as
        that sender is collected, so the cyclic collector -- which can run on
        any allocation this walk makes -- changes the mapping underneath it.
        A frame that had only asked whether anything wanted mouse moves then
        died with ``dictionary changed size during iteration``. Copying the
        keys costs a list of pointers; the receiver lists are copied only for a
        signal that already matches, which is the rare case.
        """
        for signals in list( dispatcher.connections.values() ):
            for signal, receivers in list( signals.items() ):
                if (isinstance( signal, tuple ) and signal and signal[0] == self.type
                        and any( True for _ in dispatcher.liveReceivers( list( receivers ) ) )):
                    return True
        return False
    def ProcessEvent(self, event):
        """Dispatch an incoming event

        The event must define the getKey() method.
        The event must have an attribute "type" (though the current
        implementation does not actually use this, the information
        should be available in ambiguous circumstances).
        """
        if __debug__:
            log.debug( 'ProcessEvent %r', event )
        processed = 0
        # anonymous mouse function only...
        metaKey = (self.type,0,event.getKey())
        results = dispatcher.sendExact( metaKey, None, event )
        for handler, result in results:
            if __debug__:
                log.debug( '   handler %s -> %r', handler, result )
            processed = processed or result
        if not processed:
            metaKey = (self.type,0,None)
            results = dispatcher.sendExact( metaKey, None, event )
            for handler, result in results:
                if __debug__:
                    log.debug( '   handler %s -> %r', handler, result )
                processed = processed or result
        return processed
    def registerCallback(
        cls,
        key,
        function = None,
        node = None,
        capture = 0,
    ):
        """Register callback function for the given key (possibly node-specific)

        key -- as returned by event.getKey()
        function -- callable function taking at least an
            event object as it's first parameter, or None
        node -- the node to be watched, None to register a
            context-level callback ( default )
        capture -- if true, capture events before passing to
            children, rather than processing during the
            bubbling phase.  (default false)

        Note: this method would normally be called by a sub-
            class with the calculated key for the sub-class.

        Note: the callback is connected by *weak* reference, so the caller
            must hold the only strong one -- see addEventHandler.  A function
            that nothing else refers to is collected the moment this returns
            and the binding becomes a silent no-op.  This is what allows a
            node to be collected without unbinding its handlers first.

        return previous callback function or None
        """
        previous = cls._removeCurrentCallbacks( key, node=node, capture=capture )
        if function is not None:
            metaKey = (cls.type,capture,key)
            if __debug__:
                log.info( """Register(%(capture)s): %(metaKey)r for node %(node)r -> %(function)r"""%locals())
            dispatcher.connect( function, sender=node, signal=metaKey )
            assert len(dispatcher.getReceivers(
                sender=node,
                signal=metaKey,
            )) == 1, """Have != 1 registered handlers for %(metaKey)r for node %(node)r"""%locals()
        return previous
    registerCallback = classmethod( registerCallback )
    def _removeCurrentCallbacks(
        cls, 
        key,
        node = None,
        capture = 0,
    ):
        """De-register current callbacks, return previous callback

        Note:
            There should only ever be one receiver registered
            this way, so should always be either None or the
            previous callback.
        """
        metaKey = (cls.type,capture,key)
        # remove all current watchers...
        #
        # Settled into a list before any of them is disconnected.  getReceivers
        # hands back the connection table's own list and liveReceivers walks it
        # lazily, so disconnecting from inside the walk shortens the list under
        # it: with two handlers on one key the second slides into the first's
        # place, the walk steps past it, and the check below finds a handler
        # still registered.  Two live contexts binding the same key is all it
        # takes -- which is why it showed up as an occasional failure a long
        # way from the second context that caused it.
        receivers = list(dispatcher.liveReceivers(
            dispatcher.getReceivers(
                sender=node,
                signal=metaKey,
            )
        ))
        receiver = None
        for receiver in receivers:
            if __debug__:
                log.info( """Disconnecting receiver for key %(metaKey)r for node %(node)r -> %(receiver)s"""%locals())
            dispatcher.disconnect(
                receiver,
                signal = metaKey,
                sender=node,
            )
        assert len(dispatcher.getReceivers(
            sender=node,
            signal=metaKey,
        )) == 0, """Event callback de-registration failed: %(cls)s %(key)s %(node)r"""%locals()
        return receiver
    _removeCurrentCallbacks = classmethod( _removeCurrentCallbacks )


class BubblingEventManager( EventManager ):
    """Manager base-class for events which support capture/bubbling

    Capturing/bubbling is an idea taken from the DOM2
    event API, basically, events traverse the scenegraph
    hierarchy from scenegraph to node, then back up to
    the scenegraph.  At any point, the event can have its
    stopPropagation attribute set, which will prevent
    processing the next node in the set.

    It is also possible to capture/bubble events
    "anonymously", that is, before/after the traversal
    described above (which is ~ what you get with regular
    EventManager classes (save that there are two points
    of registration, capture and bubble, and the capture
    phase can stopPropagation to avoid all further
    processing)).

    Events compatible with this manager require the following
    in addition to normal Event instances:
        stopPropagation = 0
        processMorePaths = 0
        def getObjectPaths( self ):
    the following attributes will be added during traversal:
        currentPath = ()
        currentNode = None
        atTarget = 0
    """
    type = ""
    def __init__ (self ):
        """Initialise the event manager"""
        assert self.type, """EventManager %(self)r created without a non-null "type" attribute"""%locals()
        
    def ProcessEvent( self, event ):
        """Modified version of ProcessEvent that dispatches to nodes"""
##		if self.type == "mousebutton":
##			log.setLevel( DEBUG )
##		else:
##			log.setLevel( WARN )
        
        if __debug__:
            log.debug( 'ProcessEvent %r %s', event, len(event.getObjectPaths()) )
        processed = 0
        # capturing anonymous (globally-overriding) mouse function
        metaKey = (self.type,1,event.getKey())
        results = dispatcher.sendExact( metaKey, None, event )
        for handler, result in results:
            if __debug__:
                log.debug( '   handler %s -> %r', handler, result )
            processed = processed or result
        if not event.stopPropagation:
            # general scenegraph capture/bubble operation...
            for path in self._traversalPaths(event):
                event.currentPath = path
                # if no paths, then nothing here used, of course...
                if __debug__:
                    log.debug( ' path starting %s', path )
                # do the capture pass...
                for node in path[:-1]:
                    event.currentNode = node
                    if __debug__:
                        log.debug( '   node capture pass %s', node )
                    capture = 1
                    metaKey = (self.type,capture,event.getKey())
                    results = dispatcher.sendExact( metaKey, node, event )
                    for handler, result in results:
                        if __debug__:
                            log.debug( '   handler %s -> %r', handler, result )
                        processed = processed or result
                    if event.stopPropagation:
                        break
                if not event.stopPropagation:
                    # bubbling (normal) pass
                    capture = 0
                    metaKey = (self.type,capture,event.getKey())
##					if self.type == 'mousebutton':
##						import pdb
##						pdb.set_trace()
                        
                    # atTarget is only true for first item of bubbling pass
                    event.atTarget = 1
                    for index in range( len(path)-1, -1, -1):
                        node = path[index]
                        event.currentNode = node
                        if __debug__:
                            log.debug( '   node bubble pass %s: %s,%s', node, metaKey,event )
                        results = dispatcher.sendExact( metaKey, node, event )
                        for handler, result in results:
                            if __debug__:
                                log.debug( '   handler %s -> %r', handler, result )
                            processed = processed or result
                        if event.stopPropagation:
                            break
                        event.atTarget = 0
                if processed: # something has already dealt with this event
                    if __debug__:
                        log.debug( ' processed, ProcessEvent returning')
                if not event.processMorePaths:
                    # only process up to current path...
                    break 
            # bubbling anonymous (default) mouse function
            if not event.stopPropagation:
                metaKey = (self.type,0,event.getKey())
                if __debug__:
                    log.debug( '  searching for default handler %s', metaKey )
                results = dispatcher.sendExact( metaKey, None, event )
                for handler, result in results:
                    if __debug__:
                        log.debug( '   handler %s -> %r', handler, result )
                    processed = processed or result
        return processed
    def _traversalPaths( self, event ):
        """Get the paths to traverse for a given event"""
        return event.getObjectPaths()
    
