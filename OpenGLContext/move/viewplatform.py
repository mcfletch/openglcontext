"""Mobile camera implementation using quaternions"""
from math import pi, atan
from OpenGLContext.arrays import *
from OpenGL.GLU import *
from OpenGL.GL import *
from OpenGLContext import quaternion
from vrml.vrml97 import transformmatrix

RADTODEG = 180/pi

class ViewPlatform(object):
    """Mobile Viewing Platform

    The ViewPlatform is, loosely speaking, a camera which
    sets up the projection and model-view matrices for
    an OpenGLContext scene.

    Most Context's will have an associated ViewPlatform
    thanks to the ViewPlatformMixIn class, which
    instantiates the ViewPlatform.  Shadow-rendering
    Context's will actually use a subclass which
    generates "infinite" perspective views required by
    the particular stencil-buffer shadowing algorithm.
    
    See:
        OpenGLContext.viewplatformmixin.ViewPlatformMixIn
        OpenGLContext.shadow.shadowcontext.InfViewPlatform

    Attributes:
        frustum -- OpenGL-friendly storage of frustum values,
            (field of view, aspect ratio, near, far)

        position -- object-space position of the viewing
            platform, a four-component array

        quaternion -- quaternion representing the current
            view-orientation for the viewing platform
    """
    def __init__ (
        self,
        position= (0,0,10), orientation= (0, 1, 0, 0),
        fieldOfView =pi/3,
        aspect = 1.0,
        near = 0.3, far = 50000,
    ):
        """Initialize the ViewPlatform

        position -- 3D coordinate position of the "camera"
        orientation -- VRML97-style 4-component orientation,
            that is, axis as three floats followed by radian
            rotation as a single float.
        fieldOfView -- radian angle field of view
        aspect -- float aspect ratio of window, width/height
        near -- object-space distance to the near clipping plane
        far -- object-space distance to the far clipping plane
        """
        self.setPosition(position)
        self.setOrientation(orientation)
        self.setFrustum(fieldOfView, aspect, near, far)
        
    def setFrustum( self, fieldOfView =pi/2, aspect = None, near = None, far = None):
        """Set the current frustum values for the "camera"

        fieldOfView -- radian angle field of view
        aspect -- float aspect ratio of window, width/height
        near -- object-space distance to the near clipping plane
        far -- object-space distance to the far clipping plane
        """
        if aspect is None:
            aspect = self.frustum[1]
        if near is None:
            near = self.frustum[2]
        if far is None:
            far = self.frustum[3]
        self.frustum = (fieldOfView * 180.0 / pi, aspect, near, far)
    def setViewport( self, x, y ):
        """Set the current viewport/window dimensions

        x,y -- integer width and height (respectively) of the window

        This method simply updates the frustum attribute to reflect
        the new aspect ratio.
        """
        self.frustum = (self.frustum[0] , float(x)/float(y)) + self.frustum[2:]
    def setPosition( self, position ):
        """Set the current "camera position"

        position -- 3D coordinate position to which to
            teleport the "camera"
        """
        if len(position) == 3:
            (x,y,z) = position
            # shouldn't this last value be 1.0?
            # after all, this is supposed to be an object-space coordinate
            position = array( (x,y,z,1.0),'f' )
        elif len(position) != 4:
            raise ValueError("""ViewPlatform setPosition got a position value which is neither 3 nor 4 components in length: %r"""%(position))
        else:
            position = array (position,'f')
        self.position = position
    def setOrientation(self, orientation):
        """Set the current "camera orientation"
        
        orientation -- VRML97-style 4-component orientation,
            that is, axis as three floats followed by radian
            rotation as a single float.
            
            Alternately, a quaternion.Quaternion instance
            representing the orientation.  Note that the
            orientation will likely be 180 degrees from
            what you expect, this method reverses the
            rotation value when passed a VRML97-style
            orientation.
        """
        if not isinstance( orientation, quaternion.Quaternion):
            (x,y,z,r) = orientation
            orientation = quaternion.fromXYZR( x,y,z, -r)
        self.quaternion = orientation

    def render (self, mode = None, identity=False):
        """Perform the actual view-platform setup during rendering

        This is really quite a trivial function, given the
        amount of setup that's been done before-hand.  The
        gluPerspective function takes care of the perspective-
        matrix setup, while self.quaternion (Quaternion)
        takes care of the rotation, and positioning is a
        simple call to glTranslate.

        See:
            gluPerspective
            OpenGLContext.shadow.shadowcontext.InfViewPlatform
            OpenGLContext.shadow.pinfperspective -- alternate
            gluPerspective implementation for shadowing contexts
        """
        # setup camera
        glMatrixMode(GL_PROJECTION)
        if identity:
            glLoadIdentity()
        gluPerspective(*self.frustum)
        glMatrixMode(GL_MODELVIEW)
        if identity:
            glLoadIdentity()
        x,y,z,r = self.quaternion.XYZR()
        glRotate( r*RADTODEG, x,y,z )
        glTranslate( *negative (self.position)[:3])

    def viewMatrix( self, trimDepth=None ):
        """Calculate our matrix"""
        fovy, aspect, zNear, zFar = self.frustum
        if trimDepth is not None:
            zFar = trimDepth
        return transformmatrix.perspectiveMatrix( 
            radians(fovy),
            aspect,
            zNear,
            zFar
        )
    def modelMatrix( self ):
        """Calculate our model-side matrix"""
        rotate = self.quaternion.matrix()
        # inverse of translation matrix...
        translate = transformmatrix.transMatrix(self.position)[1]
        return dot( translate,rotate )
    def matrix( self ):
        """Calculate total model-view matrix for this view platform"""
        return dot( self.modelMatrix(), self.viewMatrix())

    def getNearFar( self ):
        """Return the near and far frustum depths

        This method isn't actually used in OpenGLContext,
        as I use gluUnProject, which uses the information as
        encoded in the perspective matrix.  There are, however,
        instances where knowing the near and far clipping planes
        is useful.

        Returns the near and far values as set by the
        setFrustum method, the last two components of the
        self.frustum attribute.
        """
        return self.frustum[ -2:]

    def relativePosition( self, x=0.0,y=0.0,z=0.0 ):
        """Calculate a view-relative position from current position/orientation"""
        delta = self.quaternion * [x,y,z,0.0]
        return delta + self.position
    def relativeOrientation( self, deltaOrientation= (0,1,0,math.pi/4) ):
        """Calculate rotation within the current orientation

        In essence, this allows you to "turn your head"
        which gives you the commonly useful ability to
        function from your own frame of reference.

        For example:
            turn( 1,0,0,angle ) will rotate the camera up
                from its current view orientation
            turn( 0,1,0,angle ) will rotate the camera about
                the current horizon

        This method is implemented almost entirely within
        the quaternion class.  Quaternion's have considerable
        advantages for this type of work, as they do not
        become "warped" with successive rotations.
        """
        x,y,z,r = deltaOrientation
        x,y,z,garbage = self.quaternion * [x,y,z,0]
        return self.quaternion * quaternion.fromXYZR( x,y,z,-r)

    def moveRelative( self, x=0.0,y=0.0,z=0.0 ):
        """Move platform to a position relative to the current position

        x,y,z -- float vector along which to be moved from
            the current position within the camera orientation
        """
        self.position = self.relativePosition( x,y,z )

    def straighten( self ):
        """Re-orient the camera so the horizon is "level"

        Commonly needed after a few camera-relative orientation
        changes have built up.  This method creates a new
        orientation which is solely rotated about the y-axis,
        that is, where the camera-relative horizon matches the
        object-space horizon.
        """
        ### get the "forward" direction...
        x,y,z,w = self.quaternion * [0.0,0.0,-1.0,0.0]
        # angle around y is the x,z angle only...
        # angles should start where x = 0 and z = 1
        angle = xytoa( x,-z) - (pi/2)
        self.setOrientation( (0,1.0,0, angle) )

def xytoa( x,y ):
    """Convert an x,y coordinate to a rotation about other axis"""
    if not x:
        if y >=0:
            return math.pi/2
        else:
            return -math.pi/2
    if x > 0:
        return atan( float(y)/x)
    else:
        return pi-(atan( float(y)/x))
