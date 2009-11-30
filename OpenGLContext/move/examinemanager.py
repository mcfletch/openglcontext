"""Interaction mode for examining objects"""
from OpenGLContext.events import eventmanager

class ExamineManager ( eventmanager.EventManager):
    """Interaction EventManager for "Examine" mode

    This interaction manager implements an examine mode
    similar to that found in VRML97 browsers.  Pointing
    to an object and dragging up/down left/right causes
    the viewpoint to orbit around the object as if the
    object were held in the hand and being rotated.

    The manager uses the trackball thereby the dragwatcher
    to provide screen-relative scaling of the input.  In
    other words, distances are measured as fractions of
    the distance to the edge of the screen.
    """
    type = "examine"
    def __init__ (self, context, platform, center, event):
        """Initialise the ExamineManager

        context -- Context instance
        platform -- ViewPlatform instance
        center -- object-space coordinates about which to revolve
        event -- event which began the examine interaction.
        """
        self.platform = platform
        self.client = context
        eventmanager.EventManager.__init__ (self)
        width, height = self.client.getViewPort()
        self.button = event.button
        self.OnBuildTrackball( platform, center, event, width, height )
        self.OnBind()
    ### client API
    def update( self, event ):
        '''Update the examine trackball with new mouse event

        This updates the internal position, then triggers a
        redraw of the context.
        '''
        position, orientation = apply ( self.trackball.update, event.getPickPoint() )
        self.platform.position = position
        self.platform.quaternion = orientation
        self.client.triggerRedraw(1)
    def release( self, event ):
        """Trigger cleanup of the examine mode"""
        self.OnUnBind()
    def cancel(self, event):
        """Cancel the examine mode, return to original position and orientation"""
        position, orientation = self.trackball.cancel ()
        self.OnUnBind()
        self.platform.position = position
        self.platform.quaternion = orientation
        self.client.triggerRedraw(1)

    ### Customisation points
    def OnBuildTrackball( self, platform, center, event, width, height ):
        """Build the trackball object
        Customisation point for those wanting to use a different
        trackball implementation."""
        from OpenGLContext import trackball
        self.trackball = trackball.Trackball (
            platform.position, platform.quaternion,
            center,
            event.getPickPoint()[0],event.getPickPoint()[1],
            width, height,
        )
        
    def OnBind( self ):
        """Bind the events needing binding to run the examine mode
        Customisation point for those needing custom controls"""
        self.client.captureEvents("mousebutton", self)
        self.client.captureEvents("mousemove", self)
    def OnUnBind( self ):
        """UnBind the events for the examine mode
        Customisation point for those needing custom controls"""
        self.client.captureEvents("mousemove", None)
        self.client.captureEvents("mousebutton", None)
    def ProcessEvent (self, event):
        """Respond to events from the system
        Customisation point for those needing custom controls"""
        if event.type == "mousemove":
            self.update (event)
        elif event.type == "mousebutton":
            if event.button == self.button and event.state == 0: # mouse released
                self.release (event)
            elif event.state == 0: # mouse released, not our button, cancel
                self.cancel( event )
        