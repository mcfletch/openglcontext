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

The projection is a perspective one through the frustum, or, once
:meth:`ViewPlatform.setOrthographic` has given it a window, an orthographic
one through that window (an X3D ``OrthoViewpoint``), until the next
:meth:`ViewPlatform.setFrustum`.
"""

from math import atan, atan2, degrees, pi, tan
from collections.abc import Sequence
from typing import Any, Optional, cast

import numpy as np
from numpy import array, dot, negative, radians
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
    glOrtho,
    glMultMatrixd,
)


RADTODEG = 180 / pi

#: An orthographic window: minimum x, minimum y, maximum x, maximum y.
Window = tuple[float, float, float, float]


def fitted_window(window: Sequence[float], aspect: float) -> Window:
    """`window` widened about its centre along one axis to the shape `aspect`

    `aspect` is width over height. The whole of `window` stays in view.
    """
    left, bottom, right, top = (float(value) for value in window[:4])
    width, height = right - left, top - bottom
    if height > 0 and width > 0 and aspect > 0:
        if width / height < aspect:
            grow = (height * aspect - width) / 2.0
            left, right = left - grow, right + grow
        else:
            grow = (width / aspect - height) / 2.0
            bottom, top = bottom - grow, top + grow
    return (left, bottom, right, top)


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

    #: Vertical field of view (degrees), aspect ratio, near and far clipping
    #: distances, in the order ``gluPerspective`` takes them.
    frustum: tuple[float, float, float, float]
    #: The field of view :meth:`setFrustum` was given (radians), and the
    #: dimension of the view it spans: ``'height'``, or ``'smaller'`` (the
    #: narrower of width and height, as an X3D or VRML97 Viewpoint's does).
    fieldOfView: float = pi / 3
    across: str = 'height'
    #: Object-space position, four components.
    position: Any
    #: View orientation.
    quaternion: Quaternion
    #: The orthographic window projected through, or None for the frustum.
    window: Optional[Window] = None

    def __init__(
        self,
        position: Sequence[float] = (0, 0, 10),
        orientation: Sequence[float] | Quaternion = (0, 1, 0, 0),
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
                   far: Optional[float] = None,
                   across: str = 'height') -> None:
        """Set the current frustum values for the "camera"

        fieldOfView -- radian angle field of view
        aspect -- float aspect ratio of window, width/height
        near -- object-space distance to the near clipping plane
        far -- object-space distance to the far clipping plane
        across -- the dimension `fieldOfView` spans: 'height', or 'smaller'
            (the narrower of width and height); the frustum's own angle is
            the vertical one either way
        """
        if across not in ('height', 'smaller'):
            raise ValueError('A field of view spans the height or the smaller dimension, not %r'
                             % (across,))
        if aspect is None:
            aspect = self.frustum[1]
        if near is None:
            near = self.frustum[2]
        if far is None:
            far = self.frustum[3]
        self.fieldOfView = float(fieldOfView)
        self.across = across
        self.frustum = (self._vertical(aspect), aspect, near, far)
        self.window = None

    def _vertical(self, aspect: float) -> float:
        """The vertical angle, degrees, that gives :attr:`fieldOfView` across its dimension"""
        if self.across == 'smaller' and 0 < aspect < 1:
            return degrees(2.0 * atan(tan(self.fieldOfView / 2.0) / aspect))
        return degrees(self.fieldOfView)

    def setClipping(self, near: Optional[float] = None,
                    far: Optional[float] = None) -> None:
        """Set the clipping distances, leaving the projection as it is

        None leaves that distance as it is.
        """
        fieldOfView, aspect, oldNear, oldFar = self.frustum
        self.frustum = (fieldOfView, aspect,
                        oldNear if near is None else near,
                        oldFar if far is None else far)

    def setOrthographic(self, window: Sequence[float],
                        near: Optional[float] = None,
                        far: Optional[float] = None) -> None:
        """Project orthographically through `window` until the next :meth:`setFrustum`

        window -- minimum x, minimum y, maximum x, maximum y, in the
            platform's own coordinates; widened to the view's shape
            (:func:`fitted_window`)
        near, far -- the clipping distances; None leaves each as it is
        """
        self.setClipping(near, far)
        left, bottom, right, top = (float(value) for value in window[:4])
        self.window = (left, bottom, right, top)

    def setViewport(self, x: float, y: float) -> None:
        """Set the current viewport/window dimensions

        x,y -- integer width and height (respectively) of the window

        This method updates the frustum attribute to reflect the new aspect
        ratio, and the vertical angle where the field of view spans the
        smaller dimension.
        """
        aspect = float(x) / float(y)
        self.frustum = (self._vertical(aspect), aspect) + self.frustum[2:]

    def setPosition(self, position: Sequence[float]) -> None:
        """Set the current "camera position"

        position -- 3D coordinate position to which to
            teleport the "camera"
        """
        if len(position) == 3:
            (x, y, z) = position
            # shouldn't this last value be 1.0?
            # after all, this is supposed to be an object-space coordinate
            self.position = array((x, y, z, 1.0), "d")
        elif len(position) != 4:
            raise ValueError(
                """ViewPlatform setPosition got a position value which is neither 3 nor 4 components in length: %r"""
                % (position)
            )
        else:
            self.position = array(position, "d")

    def setOrientation(
        self, orientation: Sequence[float] | Quaternion
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

        The projection is :meth:`viewMatrix`, multiplied onto the
        projection stack, while self.quaternion (Quaternion)
        takes care of the rotation, and positioning is a
        simple call to glTranslate.

        See:
            glMultMatrix, glOrtho
        """
        # setup camera
        glMatrixMode(GL_PROJECTION)
        if identity:
            glLoadIdentity()
        if self.window is not None:
            _fov, aspect, near, far = self.frustum
            left, bottom, right, top = fitted_window(self.window, aspect)
            glOrtho(left, right, bottom, top, near, far)
        else:
            glMultMatrixd(np.asarray(self.viewMatrix(), 'd'))
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
        if self.window is not None:
            # The pass trims with a negative depth, which the perspective
            # matrix reads as a far plane at infinity; here it would turn
            # the depth range inside out, so only a positive one trims.
            far = self.frustum[3] if trimDepth is None or trimDepth <= 0 else zFar
            left, bottom, right, top = fitted_window(self.window, aspect)
            projection = transformmatrix.orthoMatrix(left, right, bottom, top, zNear, far)
            if inverse:
                return np.linalg.inv(projection).astype('f')
            return projection
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

    def getNearFar(self) -> tuple[float, float]:
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

    def forward(self) -> Any:
        """The unit direction the camera looks along, in world coordinates.

        An ``(x, y, z)`` array: where a ray cast from the view goes -- a
        hitscan shot, a pick, a line of sight -- with :attr:`position` as its
        origin.
        """
        return (self.quaternion * [0.0, 0.0, -1.0, 0.0])[:3]

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
        x, y, z = self.forward()
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
