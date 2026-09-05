"""Orbiting, dollying and panning a camera about a point.

:class:`TurntableOrbit` is the maths behind the examine gestures --
:mod:`OpenGLContext.move.examinemanager` drives it from mouse events, and
:class:`~OpenGLContext.move.movementmanager.MovementManager` binds those to the
right button, the middle button and the wheel.  It holds no GL and no window: it
is handed a camera, a pivot and pixel coordinates, and answers a new position
and orientation, so what it does is decided by numbers a test can supply.

**A turntable, not an arcball.**  Horizontal movement swings the camera about
the world's up axis and vertical movement raises and lowers it, with the
elevation stopped just short of the pole.  Yaw about a fixed up axis and pitch
about the horizontal axis across the view introduce no roll between them, so the
horizon stays where the viewer put it and the view can never come out upside
down.  The alternative -- Shoemake's arcball, which
:class:`~OpenGLContext.move.trackball.Trackball` implements -- has no preferred
up, and trades the level horizon for the freedom to spin a model end over end.
For examining a scene that stands on a ground plane the turntable is the better
default, and an application that wants the other one overrides
:meth:`~OpenGLContext.move.examinemanager.ExamineManager.OnBuildOrbit`.

**Sensitivity is uniform.**  The angle turned is proportional to the pixels
moved, at one rate over the whole window and the same rate in both directions,
with the window's *height* as the span for each axis so that a circular hand
movement traces a circular orbit.  A drag the height of the window is
:data:`DRAG_ANGLE`, half a turn.

**The aim the camera had is kept.**  The pivot is the point under the cursor,
which is rarely the centre of the screen, so a camera turned to face it squarely
would jump the moment the button went down.  The rotation between "looking at
the pivot" and "looking where you were looking" is measured once, when the drag
starts, and carried through every frame of it.
"""

from math import asin, atan2, cos, pi, radians, sin, tan

import numpy as np

from OpenGLContext import quaternion

#: Which way is up.  VRML97, glTF and every scene OpenGLContext loads agree on
#: +Y, and it is what the orbit swings about and what levels the horizon.
WORLD_UP = np.array([0.0, 1.0, 0.0], dtype='d')

#: How far a drag the height of the window turns the view: half a circle.  It
#: means the whole of an object is reachable in one drag while a small movement
#: stays a small look.
DRAG_ANGLE = pi

#: How close to straight up or straight down the camera may be driven.  At the
#: pole a look-at has no heading to choose from, and going past it is what turns
#: a view upside down.
ELEVATION_LIMIT = radians(89.9)

#: The field of view assumed when a caller names none, in radians.  Matches
#: :class:`~OpenGLContext.move.viewplatform.ViewPlatform`.
DEFAULT_FIELD_OF_VIEW = pi / 3.0

#: How near the pivot a dolly may bring the camera, in world units.  Dollying
#: through the pivot leaves the camera inside the thing it was looking at, with
#: nothing left to orbit.
MINIMUM_RADIUS = 1e-3

#: Which way to face when the view is along the up axis and a look-at has no
#: preferred heading.
FALLBACK_FORWARD = np.array([0.0, 0.0, -1.0], dtype='d')

_TINY = 1e-9


def _unit(vector, fallback):
    """``vector`` scaled to unit length, or ``fallback`` if it has none."""
    vector = np.asarray(vector, dtype='d')[:3]
    length = float(np.linalg.norm(vector))
    if length < _TINY:
        return np.asarray(fallback, dtype='d')[:3].copy()
    return vector / length


def aimAt(position, centre, up=WORLD_UP):
    """The orientation of a camera at ``position`` looking at ``centre``.

    Levelled: the camera's right axis lies in the plane perpendicular to ``up``,
    so there is no roll.  This is what every gesture here builds its orientation
    from.

    Returns a :class:`~OpenGLContext.quaternion.Quaternion` in the sense the
    view platform uses, where ``quaternion * localVector`` is that vector in
    world coordinates.
    """
    up = _unit(up, WORLD_UP)
    forward = _unit(np.asarray(centre, 'd')[:3] - np.asarray(position, 'd')[:3],
                    FALLBACK_FORWARD)
    right = np.cross(forward, up)
    if float(np.linalg.norm(right)) < _TINY:
        # Looking straight along the up axis: any heading will do, and this one
        # is stable as the camera arrives at the pole rather than swinging as
        # it crosses.
        right = np.cross(forward, FALLBACK_FORWARD)
    right = _unit(right, np.array([1.0, 0.0, 0.0]))
    trueUp = np.cross(right, forward)
    # Columns, because ``quaternion * v`` is the matrix times the vector: the
    # camera's own axes are what the local unit vectors have to map to.
    return quaternion.fromMatrix(np.column_stack([right, trueUp, -forward]))


def _axis(orientation, local):
    """One of a camera orientation's own axes, in world coordinates"""
    return np.asarray(
        orientation * np.array(tuple(local) + (0.0,), dtype='d'), dtype='d')[:3]


def _rollBetween(levelled, orientation):
    """How far ``orientation`` is rolled from ``levelled``, in radians

    A number rather than a rotation, because the axis it turns about is the
    camera's own view direction and that direction moves: kept as a rotation it
    would be about whatever the view direction was when the drag began, and
    re-applying it as the view swung round would tilt the horizon.
    """
    forward = _axis(orientation, (0.0, 0.0, -1.0))
    level, actual = _axis(levelled, (1.0, 0.0, 0.0)), _axis(orientation, (1.0, 0.0, 0.0))
    return atan2(float(np.dot(np.cross(level, actual), forward)),
                 float(np.dot(level, actual)))


def _rolled(levelled, roll):
    """``levelled`` turned ``roll`` radians about its own view direction"""
    if not roll:
        return levelled
    # The right-hand operand of this multiplication acts in world coordinates,
    # so the axis is the view direction as it is now rather than as it was.
    x, y, z = _axis(levelled, (0.0, 0.0, -1.0))
    return levelled * quaternion.fromXYZR(x, y, z, -roll)


class TurntableOrbit(object):
    """One examine gesture: where the camera goes as the pointer moves.

    Built when the button goes down and asked for a new camera on every
    movement.  Each answer is measured from where the drag *started* rather
    than from the last answer, so nothing accumulates and a drag back to the
    start point puts the view back exactly where it was.

    Attributes:
        centre -- the world point being orbited, which :meth:`pan` moves
        radius -- distance from the camera to it, which :meth:`dolly` changes
        azimuth, elevation -- where the camera stands on the sphere about the
            pivot, in radians
        startAzimuth, startElevation -- where it stood when the drag began
    """

    def __init__(
        self, position, orientation, centre,
        originalX, originalY, width, height,
        dragAngle=DRAG_ANGLE,
        up=WORLD_UP,
        fieldOfView=DEFAULT_FIELD_OF_VIEW,
        minimumRadius=MINIMUM_RADIUS,
    ):
        """Begin a gesture from where the camera is now

        position -- world position of the camera, three or four components
        orientation -- its orientation, as a
            :class:`~OpenGLContext.quaternion.Quaternion`
        centre -- the world point to orbit; see
            :meth:`OpenGLContext.context.Context.examineCenter`
        originalX, originalY -- where the drag began, in pick-point
            coordinates (pixels from the bottom left, y counting upward)
        width, height -- the size of the window, in the same pixels
        dragAngle -- how far a drag the height of the window turns the view
        up -- the world's up axis
        fieldOfView -- the camera's vertical field of view in radians, which
            sets how much world one pixel of :meth:`pan` covers
        minimumRadius -- how near the pivot a :meth:`dolly` may come
        """
        self.startPosition = np.asarray(position, dtype='d').copy()
        self.startOrientation = orientation
        self.startCentre = self._point(centre)
        self.centre = self.startCentre.copy()
        self.start = (float(originalX), float(originalY))
        # The height for both axes: measuring x against the width would turn a
        # circular hand movement into an ellipse on any window that is not
        # square.  One pixel is one angle, whichever way it moves.
        self.span = float(height) if height else 1.0
        self.dragAngle = float(dragAngle)
        self.up = _unit(up, WORLD_UP)
        self.fieldOfView = float(fieldOfView)
        self.minimumRadius = float(minimumRadius)

        # A horizontal frame to measure the azimuth in.  Any two perpendicular
        # axes will do; these are the world's own wherever up is the world's.
        self._horizontal = _unit(
            np.cross(self.up, FALLBACK_FORWARD), np.array([1.0, 0.0, 0.0]))
        self._across = np.cross(self._horizontal, self.up)

        offset = self.startPosition[:3] - self.centre[:3]
        self.radius = max(float(np.linalg.norm(offset)), self.minimumRadius)
        if float(np.linalg.norm(offset)) < _TINY:
            # Standing on the pivot: there is no orbit to speak of, so the
            # camera is placed the minimum distance behind where it is looking,
            # which leaves the view pointing the way it already pointed.
            offset = -self.radius * _unit(
                orientation * np.array([0.0, 0.0, -1.0, 0.0]), FALLBACK_FORWARD)
        direction = offset / float(np.linalg.norm(offset))
        self.startElevation = self._clampElevation(
            asin(float(np.clip(np.dot(direction, self.up), -1.0, 1.0))))
        self.startAzimuth = atan2(float(np.dot(direction, self._across)),
                                  float(np.dot(direction, self._horizontal)))
        self.azimuth, self.elevation = self.startAzimuth, self.startElevation

        # Where the camera was looking, relative to the pivot, so the drag
        # begins from the view the user had rather than snapping to the pivot.
        # Kept as a *direction* in the aim frame's coordinates plus whatever
        # roll was left over: composing the whole leftover rotation onto a
        # levelled frame tilts the horizon a little at every step, and a few
        # drags of that leaves the world visibly on the slant.
        aim = aimAt(self.startPosition, self.centre, self.up)
        # Where the camera looks, said in the aim frame's own coordinates: the
        # inverse maps a world direction back into that frame, and it has to be
        # applied to the direction rather than composed with the orientation,
        # which would be a different rotation altogether.
        self._offset = np.asarray(
            aim.inverse() * np.append(_axis(orientation, (0.0, 0.0, -1.0)), 0.0),
            dtype='d')[:3]
        self._roll = _rollBetween(self._levelled(self.startPosition),
                                  orientation)

    ### the gestures
    def rotate(self, newX, newY):
        """Swing the camera about the pivot to follow the pointer

        newX, newY -- where the pointer is now, in pick-point coordinates

        Returns the new ``(position, orientation)``.
        """
        acrossWindow, upWindow = self._fractions(newX, newY)
        self.azimuth = self.startAzimuth + acrossWindow * self.dragAngle
        # Dragging upward puts the camera below the pivot, which is the sense
        # of taking hold of the object and tipping its top toward you.
        self.elevation = self._clampElevation(
            self.startElevation - upWindow * self.dragAngle)
        return self._place()

    def dolly(self, factor):
        """Move the camera toward or away from the pivot

        factor -- what to multiply the distance by; below one moves closer.
            Multiplicative because a wheel notch means "a bit nearer" at every
            scale, and a fixed step is either nothing across a landscape or a
            leap across a teacup.

        Returns the new ``(position, orientation)``.
        """
        self.radius = max(self.radius * float(factor), self.minimumRadius)
        return self._place()

    def pan(self, newX, newY):
        """Slide the camera and the pivot together, across the view

        newX, newY -- where the pointer is now, in pick-point coordinates

        The scale is taken from the distance to the pivot and the field of
        view, so what is under the cursor stays under it.

        Returns the new ``(position, orientation)``.
        """
        acrossWindow, upWindow = self._fractions(newX, newY)
        # The world covered by the whole window's height, at the pivot's depth.
        extent = 2.0 * self.radius * tan(self.fieldOfView / 2.0)
        right = _unit(self.startOrientation * np.array([1.0, 0.0, 0.0, 0.0]),
                      np.array([1.0, 0.0, 0.0]))
        up = _unit(self.startOrientation * np.array([0.0, 1.0, 0.0, 0.0]),
                   self.up)
        # Away from the movement: the gesture takes hold of the scene and
        # carries it with the pointer, which moves the camera the other way.
        shift = -extent * (acrossWindow * right + upWindow * up)
        self.centre = self.startCentre.copy()
        self.centre[:3] += shift
        return self._place()

    def cancel(self):
        """Give back the camera exactly as this gesture was handed it"""
        return self.startPosition, self.startOrientation

    #: The generic name for "a drag has moved", which
    #: :class:`OpenGLContext.move.trackball.Trackball` answers to as well.
    update = rotate

    ### internals
    def _fractions(self, newX, newY):
        """How far the pointer has come, as a fraction of the window's height"""
        return ((float(newX) - self.start[0]) / self.span,
                (float(newY) - self.start[1]) / self.span)

    def _clampElevation(self, elevation):
        return max(-ELEVATION_LIMIT, min(ELEVATION_LIMIT, elevation))

    def _direction(self):
        """The unit vector from the pivot to the camera"""
        flat = cos(self.elevation)
        return (flat * cos(self.azimuth) * self._horizontal
                + flat * sin(self.azimuth) * self._across
                + sin(self.elevation) * self.up)

    def _levelled(self, position):
        """The level orientation looking the way the camera looks, from here

        The aim offset travels with the pivot -- the camera keeps looking the
        same amount off it -- while the horizon is rebuilt from the world's up
        axis rather than carried along, which is what stops a drag from
        gathering roll.
        """
        aim = aimAt(position, self.centre, self.up)
        forward = np.asarray(aim * np.append(self._offset, 0.0), dtype='d')[:3]
        return aimAt(position[:3], position[:3] + forward, self.up)

    def _place(self):
        """The camera that the current pivot, radius and angles describe"""
        position = self.centre.copy()
        position[:3] += self.radius * self._direction()
        position[3] = 1.0
        return position, _rolled(self._levelled(position), self._roll)

    @staticmethod
    def _point(value):
        """A world point as a four-component array, whatever length came in"""
        value = np.asarray(value, dtype='d')
        if len(value) >= 4:
            return value[:4].copy()
        point = np.ones((4,), dtype='d')
        point[:3] = value[:3]
        return point
