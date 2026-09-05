"""Interaction mode for examining objects

One drag of the mouse, from the button going down to it coming up again, driving
:class:`OpenGLContext.move.orbit.TurntableOrbit`.  Which gesture the drag is --
orbit or pan -- is settled by which button began it; the wheel dollies whether
or not a drag is in progress.  The bindings are in
:mod:`OpenGLContext.move.direct`.
"""

from OpenGLContext.events import eventmanager
from OpenGLContext.events.mouseevents import WHEEL_BUTTONS, WHEEL_UP
from OpenGLContext.move import orbit

#: Swing the camera about the pivot.
ROTATE = 'rotate'
#: Slide the camera and the pivot together, across the view.
PAN = 'pan'

#: How far a drag from where it started to the edge of the window turns the
#: view: **half a circle**.  See :data:`OpenGLContext.move.orbit.DRAG_ANGLE`.
EXAMINE_DRAG_ANGLE = orbit.DRAG_ANGLE

#: What one wheel notch multiplies the distance to the pivot by, scrolling
#: toward it.  Multiplicative, so a notch means "a bit nearer" whether the
#: camera is examining a teacup or a landscape.
DOLLY_STEP = 0.8

#: How much of the near clipping distance a dolly must leave in front of the
#: camera.  Dollying until the pivot is inside the near plane leaves the thing
#: being examined invisible, which reads as having lost it.
NEAR_PLANE_MARGIN = 2.0


def orbitFor(platform, centre, event, width, height, **named):
    """Build a :class:`~OpenGLContext.move.orbit.TurntableOrbit` for a platform

    Reads the frustum for the two things a gesture needs from it: the field of
    view, which decides how much world one pixel of a pan covers, and the near
    plane, which is how close a dolly may come to the pivot.
    """
    fieldOfView, _aspect, near, _far = platform.frustum
    x, y = event.getPickPoint()
    named.setdefault('fieldOfView', float(fieldOfView) * orbit.pi / 180.0)
    named.setdefault('minimumRadius',
                     max(float(near) * NEAR_PLANE_MARGIN, orbit.MINIMUM_RADIUS))
    return orbit.TurntableOrbit(
        platform.position, platform.quaternion, centre,
        x, y, width, height, **named)


class ExamineManager (eventmanager.EventManager):
    """Interaction EventManager for "Examine" mode

    A drag that takes hold of the scene: pointing at an object and dragging
    orbits the viewpoint about it as though the object were held in the hand
    and turned (``ROTATE``), or carries object and camera across the view
    together (``PAN``).  The wheel moves the camera toward and away from the
    pivot throughout.

    The maths is :class:`OpenGLContext.move.orbit.TurntableOrbit`, which
    measures the drag as a fraction of the window: a movement means the same
    amount wherever in the window it began.
    """
    type = "examine"

    def __init__ (self, context, platform, center, event, gesture=ROTATE):
        """Initialise the ExamineManager

        context -- Context instance
        platform -- ViewPlatform instance
        center -- object-space coordinates about which to revolve
        event -- event which began the examine interaction.
        gesture -- :data:`ROTATE` or :data:`PAN`
        """
        self.platform = platform
        self.client = context
        self.gesture = gesture
        eventmanager.EventManager.__init__ (self)
        width, height = self.client.getViewPort()
        self.button = event.button
        self.OnBuildOrbit( platform, center, event, width, height )
        self.OnBind()

    ### client API
    def update( self, event ):
        '''Update the gesture with a new mouse position

        This moves the camera, then triggers a redraw of the context.
        '''
        follow = self.orbit.pan if self.gesture == PAN else self.orbit.rotate
        self.apply( *follow( *event.getPickPoint() ) )

    def dolly( self, event ):
        """Move the camera toward or away from the pivot by one wheel notch"""
        move = getattr( self.orbit, 'dolly', None )
        if move is None:
            # A custom orbit that only knows how to turn; a notch is then
            # nothing rather than an error in the middle of somebody's drag.
            return
        self.apply( *move(
            DOLLY_STEP if event.button == WHEEL_UP else 1.0 / DOLLY_STEP ) )

    def apply( self, position, orientation ):
        """Put a camera the orbit worked out onto the platform, and redraw"""
        self.platform.position = position
        self.platform.quaternion = orientation
        self.client.triggerRedraw(1)

    def release( self, event ):
        """Trigger cleanup of the examine mode"""
        self.OnUnBind()

    def cancel(self, event):
        """Cancel the examine mode, return to original position and orientation"""
        position, orientation = self.orbit.cancel ()
        self.OnUnBind()
        self.apply( position, orientation )

    ### Customisation points
    def OnBuildOrbit( self, platform, centre, event, width, height ):
        """Build the object that turns the drag into a camera

        Customisation point for those wanting different examine behaviour.
        Whatever is stored as ``self.orbit`` needs ``rotate(x, y)`` and
        ``cancel()``, both answering ``(position, orientation)``; ``pan`` and
        ``dolly`` are asked for only by the gestures that use them.
        :class:`OpenGLContext.move.trackball.Trackball` is the free-spinning
        arcball alternative to the default turntable.
        """
        self.orbit = orbitFor( platform, centre, event, width, height )

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
            if event.button in WHEEL_BUTTONS:
                # A notch is the press *and release* of a button no mouse has.
                # Acted on once, and never as the end of the drag: read as an
                # ordinary release it is "a button other than mine came up",
                # which is the condition that cancels.
                if event.state:
                    self.dolly( event )
            elif event.button == self.button and event.state == 0: # mouse released
                self.release (event)
            elif event.state == 0: # mouse released, not our button, cancel
                self.cancel( event )
