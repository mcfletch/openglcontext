"""Mix-in class for contexts needing to control a viewplatform object"""
from OpenGLContext import interactivecontext, context
from OpenGLContext.move import viewplatform
from OpenGL.GL import *
import math
class ViewPlatformMixin(object):
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
    platform = None
    movementManager = None
    slider = None
    initialPosition = (0,0,10)
    initialOrientation = (0,1,0,0)
    def getViewPlatform( self ):
        """Customization Point: Instantiate ViewPlatform for this context

        The default implementation is to instantiate a
        viewplatform.ViewPlatform with position equal to
        self.initialPosition and orientation equal to
        self.initialOrientation.

        See:
            OpenGLContext.shadow.shadowcontext for
            example where this method is overridden
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
    def Viewpoint( self, mode = None):
        """Customization point: Sets up the projection matrix

        This implementation potentially instantiates the
        view platform object, and then calls the object's
        render method with the mode as argument.
        """
        if not self.platform:
            self.platform = self.getViewPlatform()
        self.platform.render(
            mode = mode,
        )
    def setupDefaultEventCallbacks( self, ):
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
        super( ViewPlatformMixin, self ).setupDefaultEventCallbacks()
        from OpenGLContext.move import direct, smooth
        self.setMovementManager( smooth.Smooth( self.getViewPlatform() ) )
    def setMovementManager( self, manager ):
        """Set our current movement manager"""
        if self.movementManager:
            self.movementManager.unbind( self )
        self.movementManager = manager
        self.movementManager.bind( self )
        
    def ViewPort( self, width, height ):
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
        context.Context.ViewPort( self, width, height )
