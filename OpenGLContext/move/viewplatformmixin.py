"""Mix-in class for contexts needing to control a viewplatform object"""
from typing import TYPE_CHECKING, Any, Optional, Tuple

from OpenGLContext import context
from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP
from OpenGLContext.move import viewplatform
from OpenGLContext.move.physicswalk import PhysicsWalkMixin
class ViewPlatformMixin(PhysicsWalkMixin):
    """Mix-in for Context classes providing ViewPlatform support

    The viewplatform module provides a ViewPlatform object
    which provides generic "camera" support for OpenGLContext.
    This mix-in provides Context classes with automatic support
    for instantiating and using these objects.  In particular,
    it overrides the Viewpoint customization point, dispatching
    the call to the platform's render method.

    In addition, the ViewPlatformMixin includes support for the
    view-platform-specific examine manager (which rotates the
    view platform about an object-space center).

    The getViewPlatform method performs the actual instantiation
    of the ViewPlatform, which allows a sub-classes to use
    different view-platform classes with minimal interference.

    Finally, the ViewPlatformMixin performs "default" registration
    of various event handlers using the setupDefaultEventCallbacks
    customization point.  These provide the default navigation
    controls for OpenGLContext Contexts.

    Attributes:
        platform -- the view platform instantiated by the
            context, or None if there is not yet a view
            platform instantiated (the platform is normally
            instantiated during the first rendering pass)
        movementManager -- currently bound movement manager
        initialPosition -- the initial view position used
            by the platform.
            See: ViewPlatform.setPosition
        initialOrientation -- the initial view orientation
            used by the platform.
            See: ViewPlatform.setOrientation
        STEPDISTANCE -- relative distance that each forward/
            backward/left/right step should move the camera,
            single float value.
        TURNANGLE -- relative rotational distance that each
            "turn" should rotate the camera, single float
            value in radians.
    """
    platform: Any = None
    movementManager: Any = None
    slider: Any = None
    initialPosition = (0,0,10)
    initialOrientation = (0,1,0,0)
    #: Sampled key/pointer state, built on demand.  See
    #: :mod:`OpenGLContext.events.inputstate`.
    if TYPE_CHECKING:
        # Supplied by the Context this is mixed into.  Only the ones this
        # mix-in *calls* without overriding: the three it does override reach
        # their host through ``super()``, which the type checker cannot see
        # into for a mix-in and which is marked at each call site.
        def getViewPort( self ) -> Tuple[int, int]: ...

    inputState: Any = None
    #: Drives the declared movement modes, when the context declares any.
    navigation: Any = None
    #: Last pointer position, for turning an absolute position into a delta.
    _lastPointer: Optional[Tuple[float, float]] = None
    #: Whether the backend reports pointer motion directly.  Set the first time
    #: it does, so the same motion is not counted again off the event queue.
    _directPointerMotion = False
    #: Whether the pointer is currently grabbed for a mouse-look mode.
    _pointerCaptured = False
    #: Whether something else -- an overlay being clicked -- has asked for the
    #: pointer back for the moment.
    _captureSuspended = False

    def getInputState( self ) -> Any:
        """The context's sampled input state, created on demand.

        Movement modes *sample* this once per frame rather than reacting to
        events, which is what lets several inputs act together -- walking and
        jumping in the same frame, without either having to know about the
        other.
        """
        if self.inputState is None:
            from OpenGLContext.events.inputstate import InputState
            self.inputState = InputState()
        return self.inputState

    def getNavigation( self ) -> Any:
        """The navigation manager for this context's declared modes, or None.

        A context that declares no ``movementModes`` gets None and keeps
        whatever movement manager it already had, so the older navigation
        continues to work untouched.

        The manager is re-pointed when what it drives changes, since a
        character controller usually comes into being when a world finishes
        loading -- after the context has already been navigating the camera.
        Re-pointed rather than rebuilt, so the player keeps the mode they
        chose.
        """
        definition = getattr( self, 'contextDefinition', None )
        if definition is None or not getattr( definition, 'movementModes', None ):
            return None
        platform = self.getNavigationPlatform()
        if self.navigation is None:
            from OpenGLContext.move.navigation import NavigationManager
            self.navigation = NavigationManager( definition, platform )
        elif self.navigation.platform is not platform:
            self.navigation.retarget( platform )
        return self.navigation

    def updateNavigation( self, dt: float ) -> None:
        """Give the frame to whichever declared mode is in force."""
        navigation = self.getNavigation()
        if navigation is not None:
            mode = navigation.update( dt, self.getInputState() )
            self._applyPointerCapture(
                bool( mode is not None and mode.capturePointer ) )

    def setPointerCapture( self, capture: bool ) -> bool:
        """Grab or release the pointer; False if this backend cannot.

        Passed **down the MRO** to the backend rather than answered here.  A
        mix-in is listed before the backend in every shipped context --
        ``GLFWInteractiveContext`` is ``(ViewPlatformMixin, InteractiveContext,
        GLFWContext)`` -- so a plain ``return False`` here shadows the real
        implementation and mouse-look grabs nothing on any of them.

        A backend that genuinely has no way to hide the cursor and report
        unbounded motion simply does not define this, and the False below
        stands: mouse-look then works as far as the window edge.
        """
        backend = getattr( super( ViewPlatformMixin, self ),
                           'setPointerCapture', None )
        if backend is not None:
            return bool( backend( capture ) )
        return False

    def suspendPointerCapture( self, suspend: bool ) -> None:
        """Hand the pointer back for a moment, or take it again.

        An overlay is clicked with the same pointer a mouse-look mode has
        grabbed, so opening one has to release it and closing one has to take
        it back -- without the mode having to know an overlay exists.
        """
        suspend = bool( suspend )
        if suspend == self._captureSuspended:
            return
        self._captureSuspended = suspend
        if self._pointerCaptured:
            self.setPointerCapture( not suspend )

    def _applyPointerCapture( self, wanted: bool ) -> None:
        """Ask the backend for the pointer only when the answer changes.

        A grab is a window-manager call, not something to make once a frame.
        """
        if wanted == self._pointerCaptured:
            return
        self._pointerCaptured = wanted
        if not self._captureSuspended:
            self.setPointerCapture( wanted )

    def hasMouseMoveHandlers( self ) -> bool:
        """Whether anything wants mouse-move events this frame.

        The render pass drops moves when no handler is registered for them,
        which is a real saving -- but the movement sampler consumes them
        through ``ProcessEvent`` rather than through the handler registry, so
        that test cannot see it.  While a mouse-look mode is in force the moves
        it is dropping are exactly the ones the view turns from, and the result
        is a mode that grabs the pointer and then never moves the camera.
        """
        mode = getattr( getattr( self, 'contextDefinition', None ),
                        'movementMode', None )
        if mode is not None and getattr( mode, 'capturePointer', False ):
            return True
        return bool( super( ViewPlatformMixin, self )      # type: ignore[misc]
                     .hasMouseMoveHandlers() )

    def recordPointerMotion( self, x: float, y: float ) -> None:
        """Feed the sampler pointer motion, straight from the backend.

        ``x``/``y`` are in the **pick point's** origin: pixels from the
        bottom-left, y counting *upward*.  A backend whose windowing system
        counts y downward flips it before calling.

        **Mouse-look is not picking.**  A move that arrives as a *pick* event
        is delivered only once the selection buffer resolves it, is dropped
        when the pointer is over nothing, and does not arrive at all when
        picking is switched off -- none of which has anything to do with
        turning the view.  A backend that knows where the pointer went calls
        this as it happens.

        The first call only establishes where the pointer is: otherwise
        entering a window would read as one violent flick of the view.

        **Motion is ignored while the capture is suspended**, because the
        pointer is then somebody else's -- an overlay is being clicked with it.
        A backend reports cursor motion straight to here rather than through
        the event queue, so gating ``ProcessEvent``, which is all an overlay
        can do, does not reach this path; without the test below the world
        keeps turning under the dialog the player is reading.  The position is
        still tracked, so the journey across the dialog is not delivered as one
        flick the moment the pointer is handed back.
        """
        self._directPointerMotion = True
        point = ( x, y )
        if self._lastPointer is not None and not self._captureSuspended:
            self.getInputState().mouse_moved(
                point[0] - self._lastPointer[0],
                point[1] - self._lastPointer[1] )
        self._lastPointer = point

    def forgetPointerOrigin( self ) -> None:
        """Forget where the pointer was, so the next report is only a position.

        For a backend that *moves* the pointer itself.  Warping it back to the
        middle of the window is how a windowing system with no unbounded-motion
        cursor keeps mouse-look turning past the edge of the screen, and the
        warp arrives back as an ordinary movement -- one that is exactly the
        reverse of the movement that provoked it, so counted it leaves the view
        standing still.  A backend calls this the moment it recognises its own
        warp, and the position that follows establishes where the pointer now
        is without turning anything.
        """
        self._lastPointer = None

    def _recordInput( self, event: Any ) -> None:
        """Feed one event to the sampler.

        Pointer events carry an absolute position, while mouse-look wants how
        far the pointer moved, so the delta is taken here -- for the backends
        that report motion only as events.  One that calls
        :meth:`recordPointerMotion` has already been counted, and taking the
        delta from both would turn the view twice as far as the hand moved.
        """
        kind = getattr( event, 'type', None )
        if kind in ( 'keyboard', 'keypress' ):
            self.getInputState().process( event )
        elif kind == 'mousebutton':
            # A held mouse button is an input like a held key -- in a
            # first-person game the left button is the trigger -- so it goes
            # through the same sampler under the same kind of name.  The wheel
            # is left out: its "buttons" are a spelling for a notch that is
            # never held, and one recorded here would stay down for ever.
            if getattr( event, 'button', -1 ) not in ( WHEEL_UP, WHEEL_DOWN ):
                self.getInputState().process( event )
        elif kind == 'mousemove' and not self._directPointerMotion:
            point = event.getPickPoint()
            if point:
                if self._lastPointer is not None:
                    self.getInputState().mouse_moved(
                        point[0] - self._lastPointer[0],
                        point[1] - self._lastPointer[1] )
                self._lastPointer = point
    def getViewPlatform( self ) -> Any:
        """Customization Point: Instantiate ViewPlatform for this context

        The default implementation is to instantiate a
        viewplatform.ViewPlatform with position equal to
        self.initialPosition and orientation equal to
        self.initialOrientation.

        """
        if not self.platform:
            width,height = self.getViewPort()
            if width==0 or height==0:
                aspect = 1.0
            else:
                aspect = float(width)/float(height)
            self.platform = viewplatform.ViewPlatform(
                position = self.initialPosition,
                orientation = self.initialOrientation,
                aspect = aspect,
            )
        return self.platform
    def setupDefaultEventCallbacks( self ) -> None:
        """Customization point: Setup application default callbacks

        This method binds a large number of callbacks which support
        the OpenGLContext default camera-manipulation modes.  In
        particular:
            * unmodified arrow keys for x,z (in camera coordinate
                space) movement
            * Alt+arrow keys for x,y (in camera coordinate space)
                movement
            * Ctrl+up/down arrow keys for rotating the head backward/
                forward
            * Mouse-button-2 (right) for entering "examine" mode
            * '-' for straightening the view platform
        """
        super( ViewPlatformMixin, self ).setupDefaultEventCallbacks()   # type: ignore[misc]
        from OpenGLContext.move import smooth
        self.setMovementManager( smooth.Smooth( self.getViewPlatform() ) )
    def ProcessEvent( self, event: Any ) -> Any:
        """Sample the event, then dispatch it as usual.

        Sampling here rather than through ``addEventHandler`` is deliberate:
        the sampler wants *every* key, and the handler registry is keyed by
        name/state/modifiers, so registering for "any key" is not expressible.
        """
        self._recordInput( event )
        return super( ViewPlatformMixin, self ).ProcessEvent( event )   # type: ignore[misc]

    def setMovementManager( self, manager: Any ) -> None:
        """Set our current movement manager"""
        if self.movementManager:
            self.movementManager.unbind( self )
        self.movementManager = manager
        self.movementManager.bind( self )

    def ViewPort( self, width: int, height: int ) -> None:
        """Set the size of the OpenGL rendering viewport for the context

        Because the ViewPlatform provide support for
        "constant aspect ratio" in scenes, it is necessary
        to keep the ViewPlatform updated regarding the current
        aspect ratio of the ViewPort.  This implementation
        merely calls the platform's setViewport, then
        calls the super-class ViewPort method.

        XXX
            Unfortunately, because Context objects may be
            old-style classes, we can't use super(), so
            this implementation actually calls
            context.Context.ViewPort directly.
        """
        if self.platform:
            self.platform.setViewport( width, height or 1)
        ### this is ugly for a mix-in class :(
        context.Context.ViewPort( self, width, height )   # type: ignore[arg-type]
