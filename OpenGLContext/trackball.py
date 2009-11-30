"""Classic trackball mechanism for interactive rotation"""
from math import *
from OpenGLContext.arrays import *
from OpenGL.GLU import *
from OpenGL.GL import *

from OpenGLContext import quaternion, dragwatcher

class Trackball:
    '''Trackball mechanism for interactive rotation
    
    Use the trackball utility to rotate a viewpoint
    around a fixed world-space coordinate (center).

    This trackball is a simple x/y grid of polar
    coordinates.  Dragging to the left rotates the
    eye around the object to view the left side,
    similarly for right, top, bottom.
    '''
    def __init__ (
        self, position, quaternion,
        center,
        originalX, originalY, width, height,
        dragAngle= pi*2,
    ):
        """Initialise the Trackball

        position -- object-space original position (camera pos)

        quaternion -- camera orientation as a quaternion

        originalX, originalY -- the initial screen
            coordinates of the drag
        
        width, height -- the dimensions of the screen
            (newX-originalX)/(fractional width) used by
            trackball algorithm
            
        center -- the x,y,z world coordinates around which
            we are to rotate the application will need to
            use some heuristic to determine the most appropriate
            center of rotation.  For instance, when the user
            first clicks, check for an object in the "center" of
            the display, use the center of that object (or
            possibly the midpoint between the greatest and least
            Z-buffer values) projected back into world space
            coordinates.  If there is no available object,
            potentially use the maximum and minimum of the whole
            Z buffer. If there are no rendered elements at all
            then use some multiple of the near frustum (20 or
            30, for example)
        dragAngle -- maximum rotation angle for a drag
        """
        self.watcher = dragwatcher.DragWatcher (originalX, originalY, width, height)
        self.originalPosition = position
        self.originalQuaternion = quaternion
        self.xAxis = tuple(self.originalQuaternion * [1,0,0,0])[:3]
        self.yAxis = tuple(self.originalQuaternion * [0,1,0,0])[:3]

        x,y,z = center[:3]
        self.center = array( [x,y,z,0], 'd')
        self.dragAngle = dragAngle
        self.vector = self.originalPosition - self.center 
    def cancel (self):
        """Cancel drag rotation, return pos,quat to original values"""
        return self.originalPosition, self.originalQuaternion
        
    def update( self, newX, newY ):
        """Update with new x,y drag coordinates

        newX, newY -- the new screen coordinates for the drag

        returns a new position and quaternion orientation
        """
        # get the drag fractions
        x,y = self.watcher.fractions ( newX, newY )
        # multiply by the maximum drag angle
        # note that movement in x creates rotation about y & vice-versa
        # note that OpenGL coordinates make y reversed from "normal" rotation
        yRotation,xRotation = x * self.dragAngle, -y * self.dragAngle
        # calculate the results, keeping in mind that translation in one axis is rotation around the other
        xRot = apply(quaternion.fromXYZR, self.xAxis + (xRotation,))
        yRot = apply(quaternion.fromXYZR, self.yAxis + (yRotation,))

        # the vector is already rotated by originalQuaternion
        # and positioned at the origin, so just needs
        # the adjusted x + y rotations + un-positioning
        a = ((xRot *yRot) * self.vector) +  self.center
        b = self.originalQuaternion *xRot *yRot
        return a,b
        