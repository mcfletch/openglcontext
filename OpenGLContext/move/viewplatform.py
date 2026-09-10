"""The camera as a position and an orientation, and the matrices from them.

A :class:`ViewPlatform` is where the viewer stands and which way they face.  It
holds a position, an orientation as a quaternion, and the four numbers that
describe the frustum, and it turns those into the projection and model-view
matrices a pass renders through.  Orientation is a quaternion rather than
Euler angles because the platform is composed with and interpolated toward
other orientations -- following a target, snapping to a viewpoint -- and angles
gimbal-lock where quaternions do not.

A context reaches one through
:class:`~OpenGLContext.move.viewplatformmixin.ViewPlatformMixin`, which every
interactive context mixes in; the movement modes in
:mod:`OpenGLContext.move.modes` drive it, and the editor views in
:mod:`OpenGLContext.edit` subclass it to look at a world from overhead or from
a fixed orbit.
"""

from math import atan2, pi
from typing import Any, Optional, Sequence, Tuple, Union, cast

from OpenGLContext.arrays import array, negative, radians, dot
from OpenGLContext import quaternion
from OpenGLContext.quaternion import Quaternion
from vrml.vrml97 import transformmatrix

from OpenGL.GL import (
    glMatrixMode,
    GL_PROJECTION,
    glLoadIdentity,
    GL_MODELVIEW,
    glRotate,
    glTranslate,
)
from OpenGL.GLU import gluPerspective


RADTODEG = 180 / pi


class ViewPlatform(object):
    """Where the viewer stands and which way they face

    The ViewPlatform is the camera: it sets up the projection and model-view
    matrices for an OpenGLContext scene.

    Most contexts have one, built for them by
    :class:`~OpenGLContext.move.viewplatformmixin.ViewPlatformMixin`.  Reach it
    as ``context.platform``, and move it with the movement modes rather than by
    writing the fields, so that collision and the world's own constraints still
    apply.

    Attributes:
        frustum -- OpenGL-friendly storage of frustum values,
            (field of view, aspect ratio, near, far)

        position -- object-space position of the viewing
            platform, a four-component array

        quaternion -- quaternion representing the current
            view-orientation for the viewing platform
    """

    #: Field of view (degrees), aspect ratio, near and far clipping distances,
    #: in the order ``gluPerspective`` takes them.
    frustum: Tuple[float, float, float, float]
    #: Object-space position, four components.
    position: Any
    #: View orientation.
    quaternion: Quaternion

    def __init__(
        self,
        position: Sequence[float] = (0, 0, 10),
        orientation: Union[Sequence[float], Quaternion] = (0, 1, 0, 0),
        fieldOfView: float = pi / 3,
        aspect: float = 1.0,
        near: float = 0.3,
        far: float = 50000,
    ) -> None:
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

    def setFrustum(self, fieldOfView: float = pi / 2,
                   aspect: Optional[float] = None,
                   near: Optional[float] = None,
                   far: Optional[float] = None) -> None:
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

    def setViewport(self, x: float, y: float) -> None:
        """Set the current viewport/window dimensions

        x,y -- integer width and height (respectively) of the window

        This method simply updates the frustum attribute to reflect
        the new aspect ratio.
        """
        self.frustum = (self.frustum[0], float(x) / float(y)) + self.frustum[2:]

    def setPosition(self, position: Sequence[float]) -> None:
        """Set the current "camera position"

        position -- 3D coordinate position to which to
            teleport the "camera"
        """
        if len(position) == 3:
            (x, y, z) = position
            # shouldn't this last value be 1.0?
            # after all, this is supposed to be an object-space coordinate
            self.position = array((x, y, z, 1.0), "f")
        elif len(position) != 4:
            raise ValueError(
                """ViewPlatform setPosition got a position value which is neither 3 nor 4 components in length: %r"""
                % (position)
            )
        else:
            self.position = array(position, "f")

    def setOrientation(
        self, orientation: Union[Sequence[float], Quaternion]
    ) -> None:
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
        if isinstance(orientation, Quaternion):
            self.quaternion = orientation
        else:
            (x, y, z, r) = orientation
            self.quaternion = quaternion.fromXYZR(x, y, z, -r)

    def render(self, mode: Any = None, identity: bool = False) -> None:
        """Perform the actual view-platform setup during rendering

        This is really quite a trivial function, given the
        amount of setup that's been done before-hand.  The
        gluPerspective function takes care of the perspective-
        matrix setup, while self.quaternion (Quaternion)
        takes care of the rotation, and positioning is a
        simple call to glTranslate.

        See:
            gluPerspective
        """
        # setup camera
        glMatrixMode(GL_PROJECTION)
        if identity:
            glLoadIdentity()
        gluPerspective(*self.frustum)
        glMatrixMode(GL_MODELVIEW)
        if identity:
            glLoadIdentity()
        x, y, z, r = self.quaternion.XYZR()
        glRotate(r * RADTODEG, x, y, z)
        glTranslate(*negative(self.position)[:3])

    def viewMatrix(self, trimDepth: Optional[float] = None,
                   inverse: bool = False) -> Any:
        """Calculate our matrix"""
        fovy, aspect, zNear, zFar = self.frustum
        if trimDepth is not None:
            zFar = trimDepth
        return transformmatrix.perspectiveMatrix(
            radians(fovy),
            aspect,
            zNear,
            zFar,
            inverse=inverse,
        )

    def modelMatrix(self, inverse: bool = False) -> Any:
        """Calculate our model-side matrix"""
        rotate = self.quaternion.matrix(inverse=inverse)
        # inverse of translation matrix, if inverse, need the forward...
        translate = transformmatrix.transMatrix(self.position)[(not inverse)]
        if rotate is not None and translate is not None:
            if inverse:
                return dot(rotate, translate)
            else:
                return dot(translate, rotate)
        elif rotate is None:
            return translate
        else:
            return rotate

    def matrix(self, inverse: bool = False) -> Any:
        """Calculate total model-view matrix for this view platform"""
        model = self.modelMatrix(inverse=inverse)
        view = self.viewMatrix(inverse=inverse)
        if model is not None and view is not None:
            if inverse:
                return dot(view, model)
            else:
                return dot(model, view)
        elif model is None:
            return view
        else:
            return model

    def getNearFar(self) -> Tuple[float, float]:
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
        return self.frustum[-2:]

    def relativePosition(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Any:
        """Calculate a view-relative position from current position/orientation"""
        delta = self.quaternion * [x, y, z, 0.0]
        return delta + self.position

    def relativeOrientation(
        self, deltaOrientation: Sequence[float] = (0, 1, 0, pi / 4)
    ) -> Quaternion:
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
        x, y, z, r = deltaOrientation
        x, y, z, garbage = self.quaternion * [x, y, z, 0]
        return cast(Quaternion, self.quaternion * quaternion.fromXYZR(x, y, z, -r))

    def moveRelative(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        """Move platform to a position relative to the current position

        x,y,z -- float vector along which to be moved from
            the current position within the camera orientation
        """
        self.position = self.relativePosition(x, y, z)

    def straighten(self) -> None:
        """Re-orient the camera so the horizon is "level"

        Commonly needed after a few camera-relative orientation
        changes have built up.  This method creates a new
        orientation which is solely rotated about the y-axis,
        that is, where the camera-relative horizon matches the
        object-space horizon.
        """
        ### get the "forward" direction...
        x, y, z, w = self.quaternion * [0.0, 0.0, -1.0, 0.0]
        # angle around y is the x,z angle only...
        # angles should start where x = 0 and z = 1
        angle = xytoa(x, -z) - (pi / 2)
        self.setOrientation((0, 1.0, 0, angle))


def xytoa(x: float, y: float) -> float:
    """Convert an x,y coordinate to a rotation about the other axis

    The bearing of the vector, in radians, over the whole circle: an angle
    good only within a half-turn would put a camera facing backwards for half
    of the compass.
    """
    return atan2(float(y), float(x))
